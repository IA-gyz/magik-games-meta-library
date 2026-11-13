"""RapidAPI quota observations, conservative reservations and a persistent work queue.

Only allowlisted numeric quota headers are saved. This is a last-observed balance,
not a billing guarantee when other clients share a subscription.
"""
import hashlib
import json
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from web_sessions import auth_dir, atomic_json

LOCK = threading.RLock()
RESERVE = 2


class QuotaPaused(Exception):
    pass


def parse_headers(headers, now=None):
    now = time.time() if now is None else now
    headers = {str(k).lower(): str(v) for k, v in headers.items()}
    result = {}
    for key, text in headers.items():
        match = re.fullmatch(r'(x-ratelimit-[a-z0-9-]+|x-rapidapi-[a-z0-9-]+|x-rate-limit-rapid-free-plans-hard-limit)-remaining', key)
        if not match or not text.isascii() or not text.isdecimal() or len(text) > 12:
            continue
        base = match[1]
        bucket = {'remaining': int(text), 'observed': now}
        for suffix in ('limit', 'reset'):
            value = headers.get(base + '-' + suffix, '')
            if value.isascii() and value.isdecimal() and len(value) <= 12 and (suffix != 'reset' or int(value) <= 366 * 86400):
                bucket['reset_at' if suffix == 'reset' else 'limit'] = now + int(value) + 5 if suffix == 'reset' else int(value)
        if 'limit' in bucket:
            bucket['remaining'] = min(bucket['remaining'], bucket['limit'])
        result[base] = bucket
    return result


class Quota:
    def __init__(self, options):
        fingerprint = hashlib.sha256(str(options.get('opencritic_api_key', '')).encode()).hexdigest()
        self.path = auth_dir(options) / ('opencritic-quota-' + fingerprint + '.json')

    @contextmanager
    def state(self):
        with LOCK:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            lockpath = self.path.with_suffix('.lock')
            with lockpath.open('a') as lock:
                lockpath.chmod(0o600)
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    try:
                        value = json.loads(self.path.read_text())
                        if not isinstance(value, dict):
                            raise ValueError()
                    except FileNotFoundError:
                        value = {}
                    except (ValueError, OSError):
                        raise QuotaPaused('The saved OpenCritic quota file cannot be read. No request was sent; check the quota file in the account data folder.') from None
                    yield value
                    atomic_json(self.path, value)
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def request(self, cancel):
        # Serialize local clients through response observation, avoiding stale in-flight balances.
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.path.with_suffix('.request-lock')
        with path.open('a') as lock:
            path.chmod(0o600)
            while True:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if cancel.wait(0.1):
                        from connector_io import Cancelled
                        raise Cancelled()
            try:
                self.reserve()
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def observe(self, headers):
        observed = parse_headers(headers)
        if not observed:
            return
        now = time.time()
        with self.state() as state:
            buckets = state.setdefault('buckets', {})
            buckets.update(observed)
            state['checked'] = now
            # A reset verification is complete only if every old bucket was updated.
            if set(buckets).issubset(observed):
                state.pop('verification_pending', None)

    def access_result(self, success):
        with self.state() as state:
            state['access_ok'] = success is True

    @staticmethod
    def blocked(state, now):
        result = []
        for bucket in state.get('buckets', {}).values():
            if bucket.get('remaining', 0) <= RESERVE:
                result.append(bucket)
        return result

    def reserve(self, count=1):
        now = time.time()
        with self.state() as state:
            if state.get('blocked_until', 0) > now:
                raise QuotaPaused('OpenCritic is waiting after a rate-limit response.')
            buckets = state.get('buckets', {})
            if state.get('verification_pending'):
                raise QuotaPaused('OpenCritic needs fresh quota headers after reset before more calls can be sent.')
            blocked = [b for b in buckets.values() if b.get('remaining', 0) < RESERVE + count]
            if blocked:
                # After a reported reset, one useful request can verify the new balance.
                expired = all(b.get('reset_at', float('inf')) <= now for b in blocked)
                if expired and count == 1 and not state.get('verification_pending'):
                    state['verification_pending'] = True
                else:
                    raise QuotaPaused('OpenCritic paused to preserve the remaining allowance. Waiting for the reported quota reset or fresh quota information.')
            if count == 1:
                for bucket in buckets.values():
                    bucket['remaining'] = max(0, bucket.get('remaining', 0) - 1)
                state['last_attempt'] = now

    def preflight_game(self):
        # Two calls normally cover search + details. This only checks, not reserves.
        with self.state() as state:
            now = time.time()
            for bucket in state.get('buckets', {}).values():
                if bucket.get('remaining', 0) < RESERVE + 2 and bucket.get('reset_at', float('inf')) > now:
                    raise QuotaPaused('OpenCritic is waiting: fewer than two usable calls remain after the reserve.')

    def snapshot(self):
        with self.state() as state:
            return json.loads(json.dumps(state))

    def rate_pause(self, seconds):
        with self.state() as state:
            state['blocked_until'] = time.time() + max(60, seconds)

    def enqueue(self, rows, for_budget=False):
        with self.state() as state:
            existing = [tuple(v) for v in state.get('queue', [])]
            existing.extend((r['store'], str(r['id'])) for r in rows)
            state['queue'] = [list(v) for v in dict.fromkeys(existing)]
            buckets = list(state.get('buckets', {}).values())
            if for_budget and buckets and all(b.get('remaining', 0) >= RESERVE + 2 for b in buckets) and not state.get('verification_pending'):
                state['queue_after'] = max(time.time() + 60, state.get('blocked_until', 0))
                return
            blocked = [b for b in buckets if b.get('remaining', 0) < RESERVE + 2]
            resets = [b.get('reset_at') for b in blocked]
            if state.get('blocked_until', 0) > time.time():
                resets.append(state['blocked_until'])
            state['queue_after'] = max(resets) if resets and all(resets) and not state.get('verification_pending') else None

    def completed(self, row):
        with self.state() as state:
            key = [row['store'], str(row['id'])]
            state['queue'] = [v for v in state.get('queue', []) if v != key]
            if not state['queue']:
                state.pop('queue_after', None)

    def clear_queue(self):
        with self.state() as state:
            state.pop('queue', None)
            state.pop('queue_after', None)

    def take_ready(self):
        with self.state() as state:
            due = state.get('queue_after')
            if not state.get('queue') or not due or due > time.time():
                return []
            rows = list(state['queue'])
            state['queue_after'] = time.time() + 3600  # retry lease if the worker cannot start/finish
            return rows


def describe(state):
    from date_display import friendly_date
    def date(value):
        return friendly_date(datetime.fromtimestamp(value, timezone.utc).isoformat()) if value else '—'
    access = 'Succeeded' if state.get('access_ok') is True else 'Failed' if state.get('access_ok') is False else 'Not verified yet'
    lines = ['OpenCritic / RapidAPI quota', 'Last quota headers received: ' + date(state.get('checked')), 'Most recent API access: ' + access]
    for name, bucket in state.get('buckets', {}).items():
        label = name.replace('x-ratelimit-', '').replace('x-rate-limit-', '')
        lines.append(f"{label}: {bucket.get('remaining', '—')} remaining / {bucket.get('limit', '—')} · reset {date(bucket.get('reset_at'))}")
    if not state.get('buckets'):
        lines.append('No usable quota headers received yet. The manual per-fetch cap applies.')
    lines += [f'{RESERVE} calls are kept in reserve.', f"{len(state.get('queue', []))} queued library entries."]
    if state.get('queue'):
        lines.append('Earliest automatic continuation: ' + date(state.get('queue_after')))
    lines.append('Last-observed balance, adjusted for local attempts. Other applications may use the same quota. Connection checks use this same tracker. Missing reset information prevents automatic continuation.')
    return '\n\n'.join(lines)

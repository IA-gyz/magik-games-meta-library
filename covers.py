"""Demand-driven cover downloads, bounded caches and delayed retry notifications."""

import hashlib
import math
import tempfile
import time
from collections import OrderedDict, deque
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QUrl, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from cover_retry import cover_retry_delay

MAX_COVER_BYTES = 8 * 1024 * 1024


class Covers(QNetworkAccessManager):
    ready = Signal(str)

    def __init__(self, directory, parent=None):
        super().__init__(parent)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.memory = OrderedDict()
        self.queued = set()
        self.queue = deque()
        self.running = 0
        self.failures = {}
        self.saved = 0
        self.retry_timer = QTimer(self)
        self.retry_timer.setSingleShot(True)
        self.retry_timer.timeout.connect(self.retry_due)
        self.prune()
        self.setTransferTimeout(20000)

    def prune(self):
        try:
            files = sorted(
                (
                    (p.stat().st_mtime, p.stat().st_size, p)
                    for p in self.directory.glob("*.png")
                ),
                key=lambda x: x[0],
            )
            total = sum(v[1] for v in files)
            for _, size, path in files:
                if total <= 256 * 1024 * 1024:
                    break
                path.unlink(missing_ok=True)
                total -= size
        except OSError:
            pass

    def path(self, url):
        return self.directory / (hashlib.sha256(url.encode()).hexdigest() + ".png")

    def remember(self, url, pix):
        self.memory[url] = pix
        self.memory.move_to_end(url)
        while len(self.memory) > 160:
            self.memory.popitem(last=False)

    def get_cover(self, url):
        if not isinstance(url, str) or not url.startswith("https://"):
            return None
        if url in self.memory:
            self.memory.move_to_end(url)
            return self.memory[url]
        path = self.path(url)
        if path.is_file():
            pix = QPixmap(str(path))
            if not pix.isNull():
                self.remember(url, pix)
                self.failures.pop(url, None)
                self.schedule_retry_notification()
                return pix
        failure = self.failures.get(url)
        if url not in self.queued and (
            failure is None or time.monotonic() >= failure["retry_at"]
        ):
            self.queued.add(url)
            self.queue.append(url)
            self.pump()
        return None

    def pump(self):
        while self.running < 4 and self.queue:
            url = self.queue.popleft()
            self.running += 1
            reply = self.get(QNetworkRequest(QUrl(url)))
            reply.setReadBufferSize(10 * 1024 * 1024)
            reply.downloadProgress.connect(
                lambda received, total, r=reply: self.check_download_size(
                    r, received, total
                )
            )
            reply.finished.connect(lambda r=reply, u=url: self.finish(r, u))

    @staticmethod
    def check_download_size(reply, received, total):
        if received > MAX_COVER_BYTES or total > MAX_COVER_BYTES:
            reply.setProperty("cover_size_exceeded", True)
            reply.abort()

    def record_failure(self, url, reply, *, invalid_image=False):
        attempt = self.failures.get(url, {}).get("attempt", 0) + 1
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        header = bytes(reply.rawHeader(b"Retry-After")).decode("ascii", errors="ignore")
        delay = cover_retry_delay(attempt, status, header, invalid_image=invalid_image)
        self.failures[url] = {
            "attempt": attempt,
            "retry_at": time.monotonic() + delay,
            "notified": False,
        }
        self.schedule_retry_notification()

    def schedule_retry_notification(self):
        deadlines = [
            value["retry_at"]
            for value in self.failures.values()
            if not value["notified"]
        ]
        if not deadlines:
            self.retry_timer.stop()
            return
        seconds = max(0.001, min(2_147_483.647, min(deadlines) - time.monotonic()))
        delay = min(2_147_483_647, math.ceil(seconds * 1000))
        self.retry_timer.start(delay)

    def retry_due(self):
        now = time.monotonic()
        due = [
            url
            for url, value in self.failures.items()
            if not value["notified"] and value["retry_at"] <= now
        ]
        for url in due:
            self.failures[url]["notified"] = True
        self.schedule_retry_notification()
        # Repainting requests only covers still needed by the selected game or visible grid.
        for url in due:
            self.ready.emit(url)

    def save_pixmap(self, url, pix):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.directory, prefix=".cover-", suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
            if pix.save(str(temporary), "PNG"):
                temporary.replace(self.path(url))
                self.saved += 1
                if self.saved % 32 == 0:
                    self.prune()
        except OSError:
            pass  # A usable image stays in memory even if the disk cache is unwritable.
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def finish(self, reply, url):
        try:
            if reply.error() != QNetworkReply.NoError:
                self.record_failure(
                    url,
                    reply,
                    invalid_image=bool(reply.property("cover_size_exceeded")),
                )
                return
            data = reply.readAll()
            pix = QPixmap()
            if len(data) > MAX_COVER_BYTES or not pix.loadFromData(data):
                self.record_failure(url, reply, invalid_image=True)
                return
            pix = pix.scaled(480, 640, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.remember(url, pix)
            self.failures.pop(url, None)
            self.schedule_retry_notification()
            self.save_pixmap(url, pix)
        finally:
            self.queued.discard(url)
            self.running -= 1
            reply.deleteLater()
            self.ready.emit(url)
            self.pump()

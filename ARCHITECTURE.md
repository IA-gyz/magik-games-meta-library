# Magik Games Library architecture

## Starting the app

`run.sh` invokes `app.py`. The entry point registers the existing KDE identity, creates QApplication and opens the main window. Shared identity constants live in `app_config.py`; changing the version must not change APP_ID or the QSettings organization/application names.

## UI boundaries

| Module | Responsibility |
| --- | --- |
| `main_window.py` | Compose the UI, connect actions, maintain selection and browsing state |
| `catalog_model.py` | Column definitions, display formatting, sorting and filtering model |
| `source_dialog.py` | Source configuration, session connection controls, secret reveal action |
| `report_dialogs.py` | Read-only installation, acquisition and metadata report dialogs |
| `sync_worker.py` | Run background sync, metadata enrichment and installation scans; emit OperationResult |
| `provider_registry.py` | Canonical provider order, source fields and sync/launch/metadata capabilities |
| `providers/` | Individual Steam, GOG, Epic, Amazon, EA and Rockstar connector implementations |
| `connector_io.py` | Shared HTTP/helper transport, ConnectorIO dependency object and exception types |
| `connectors.py` | Stable public wrappers and provider dispatch table |
| `catalog_data.py` | Catalog fields, normalization and acquisition-date provenance |
| `storage.py` | SQLite operations, refresh transaction and manual-date writes |
| `core.py` | Compatibility imports for catalog and Database APIs |
| `contracts.py` | Qt-free LogEntry, Severity, OperationResult and provider batch/result types |
| `library_service.py` | Validate provider batches, save acquisition reports and rows, produce refresh summaries |
| `settings_store.py` | Read/write existing JSON settings without changing keys or formats |
| `ui_actions.py` | Construct buttons with explicit semantic action roles |
| `appearance.py` | Theme/palette selection and direct widget styling |
| `log_view.py` | Escape and render activity messages with theme-aware colours |
| `widgets.py` | Facet picker and cover loading/delegate |
| `launch_ui.py`, `date_ui.py`, `session_ui.py` | Dedicated launch, manual-date and sign-in dialogs |

Models and dialogs do not import the main window or entry point. Background orchestration does not import UI widgets. Qt-free connectors retain their callable signatures and list-compatible return data. The shared service converts each result into a validated LibraryResult. Persistence and installation scan interfaces remain compatible. New button labels must not determine behaviour or colours: use `action_button(text, role)` or `set_button_role(button, role)` for subclasses. Standard dialog buttons receive the neutral settings role.

The toolbar keeps frequently used buttons on two rows and moves secondary actions into a Tools `QPushButton` with a `QMenu`; its disabled actions participate in the same `self.buttons` busy list as regular buttons (`QAction.setEnabled` shares the API). Window sizing is guarded in two ways: rows have no dynamic button text that can widen the layout (the OpenCritic quota badge is a menu action), and `Window.clamp_to_screen` runs on `showEvent`, capping the frame to the screen's available geometry unless maximized, fullscreen or minimized. The window may still refuse to shrink below its layout minimum; the layout minimum is kept near 1200 px so that floor fits normal screens.

Available roles: `sync`, `metadata` (including reports), `filter`, `file`, `settings`, `launch`, `danger`. Disabled controls stay muted. Appearance applies styles directly to each button and refreshes existing widget palettes, including labels with their own styles. Native widget styles therefore do not need to honour a dynamic-property selector for colours to become visible. The global theme defaults to System; light/dark overrides remain confined to this app.

## Data boundaries

`core.py` is the compatibility import surface. `catalog_data.py` owns normalization and fields; `storage.py` owns SQLite and retains the schema, metadata and acquisition report payload formats. `connectors.py` forwards to `providers/`; each implementation receives a ConnectorIO dependency explicitly. `connector_io.py` owns HTTP/helper mechanics and shared error types. `acquisition.py`, `steam_dates.py`, `epic_metadata.py` and `web_sessions.py` retain their acquisition, metadata and authentication protocols. `installations.py` discovers and validates existing installations. Launching remains a fixed argument-vector handoff rather than a shell command.

The consolidation does not migrate SQLite records or rename settings. Library data stays under `$XDG_DATA_HOME/magik-games-library` (default `~/.local/share/magik-games-library`). Credentials remain in the existing auth directory. QSettings remains organization `Magik`, application `GamesLibrary`. KDE keeps desktop identity `magik-games-library`. Existing acquisition provenance and manual overrides remain authoritative.

The user confirmed Steam date coverage and KDE pinning work before this release. Their network/matching and desktop association behaviour should be kept stable during subsequent refactoring.

## Validation

```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -q
python -m compileall -q .
```

Qt rendering tests verify that each palette changes actual button pixels in System, Light and Dark modes. Other UI tests cover source dialogs, launching, selection, presets, persistent column changes and literal log rendering. Mocked network tests cover acquisition matching and failure paths; they do not validate live accounts.

## Result and log contracts

`LibraryRows` is a list-compatible provider batch with an optional acquisition report, including for zero rows. New providers can return `LibraryResult` directly; existing providers use the list-compatible bridge. `LibraryResult.from_provider` validates records and store identity, copies the report and strips any legacy per-game `_acquisition_report` without mutating the input. `library_service.refresh_store` owns the common summary/persistence path. It invokes `Database.save_refresh` once; cancellation after a query or at the pre-commit guard prevents a new committed batch.

Date-added lookups outrank other downloads. `refresh_store` accepts an optional `reports` mapping and records the batch's acquisition report for the caller. `steam_dates` applies every cached package mapping before issuing requests and orders uncached lookups so licenses without explicit app IDs (the only date evidence for those games) are requested first; a 429 rate limit stops further requests but never discards already applied mappings. Its report carries `postponed_packages` and `date_fetch_incomplete`. `sync_worker` collects those reports during sync and, when a store still has postponed lookups, skips the automatic post-refresh enrichment and logs a warning instead; explicit enrich/retry modes and selected-game fetches are never gated.

`LogEntry` carries message text, an explicit Severity and an optional source. `OperationResult` carries worker completion events and cancellation/failure flags. QThread emits it through a Python-object signal; the UI renders it without interpreting message wording. `SummaryMessages` preserves metadata's list-of-strings API while adding typed events derived from actual counters. Plain strings appended directly to ColorLog default to information; there is no keyword severity detection.

`Database.status` adds severity to its existing JSON payload, not to the SQL schema. Old payloads without severity remain valid. The main window hydrates saved statuses once at startup; reloading game data does not replace session history. Launch handoff files retain their existing plain-text format. Session activity is limited to the latest 1,500 lines in memory.

## Provider registry and transport boundary

ProviderSpec entries define stable store names/order, the public fetch function name, source option keys/labels/kinds, optional metadata function name, sync/launch eligibility and whether a returned library is complete. Core derives STORES from this registry. UI source fields and launch controls, worker selection, connector/metadata dispatch and reconciliation completeness consume those definitions. Rockstar stays disabled for sync/launch and partial for ownership reconciliation.

The public wrappers in `connectors.py` preserve prior signatures. Each call creates an immutable ConnectorIO with the current public request/helper/token-file callables, then invokes its provider module. Late binding keeps HTTP mocks and explicit dependency injection effective. Providers import shared error types from connector_io; those same class objects are re-exported by connectors so error categorization stays consistent across acquisition, enrichment and UI code. Provider modules never import the entry point or main window.

Adding a provider requires a registry entry, its protocol implementation and public wrapper; metadata implementations also need to be available to enrichment's dispatch builder. Store names, option keys and completeness semantics are persisted interfaces: do not rename or change them during a structural refactor. Acquisition queries must remain optional and must not convert release/sync dates into ownership dates.

## Storage transaction boundary

`Database.save_refresh` acquires `BEGIN IMMEDIATE` before reading cached game payloads. The shared `_write_rows` merge/reconciliation logic, optional `_write_acquisition_report` and `_write_status` all use that connection. Successful status/report payloads share a timestamp. The context commits only after the optional cancellation guard returns. Exceptions from serialization, writes or the guard roll back all parts. Reports are preserved when no new report is supplied; a complete empty library still marks cached ownership rows inactive without deleting them. Partial library results retain their existing reconciliation semantics.

`Database.save` uses the same merge helper and acquires the writer lock before the read/merge/write sequence. `set_manual_date` similarly reads the latest payload under a writer lock and supports explicit None clearing. UI code does not execute SQL to change acquisition dates. Standalone installation snapshots, metadata results and acquisition reports retain their existing methods.

The worker may write a failure status in a separate operation after a refresh transaction rolls back. That describes the failed attempt; it must not overwrite the previous acquisition report or reconcile previous games. No network requests run inside a database transaction. Tests inject failures after SQL writes, check reader isolation, and coordinate concurrent refresh/manual-edit threads against a real temporary SQLite database.

## Consolidation status

The passes establish UI/model/dialog, worker/service/result, provider/transport and catalog/storage boundaries. Existing behavior is the baseline. Further restructuring should respond to a concrete feature or maintenance need rather than splitting methods into arbitrary mixins. Main-window browsing and launch actions can stay together until an independent controller interface is justified.

## Launch boundary

`launch_ui.py` owns configuration dialogs and preserves compatibility imports. `launch_commands.py` validates local overrides and selects installed entries eligible for launch using the provider registry. `launch_service.py` validates installation evidence and hands literal argument vectors to detached QProcess instances. No shell is invoked. Its typed event signal carries explicit severity to the activity log; the legacy text signal and plain-text rotating launch log remain available. Failed UI handoffs are logged with ERROR severity. Selection and Play consume the same readiness helper; execution still validates the installation and executable at launch time.

## Browsing state boundary

`browsing_state.py` is Qt-free and normalizes saved snapshots and named presets. The main window validates both startup state and preset application through it. Non-mapping payloads, malformed filter fields and invalid scalar types fall back to defaults. Valid facet strings and selections remain available even when the current catalog does not contain them. This does not modify source options, credentials, settings keys or the JSON storage format. `browsing.py` continues to own matching and facet tokenization.

## Completion and follow-up boundary

`operation_policy.py` owns completion-message precedence and the sync-to-scan policy without Qt. Main-window wiring retains the completed OperationResult and schedules a scan only after non-cancelled sync completion. The queued callback rechecks worker identity, thread completion, cancellation and accepted window closure before starting. This avoids starting stale follow-ups after a newer operation, a late stop request or a close. Partial source errors still allow scanning saved libraries. The existing close-during-work behavior remains: request cancellation and keep the window open until the request finishes.

## Configuration shape boundary

`configuration.py` normalizes source options, installation links and per-game launch overrides before UI construction. Text option keys derive from the provider registry plus installation/session settings; Boolean keys require actual True. Disabled provider capabilities remain authoritative. Unknown options are copied for compatibility. No file existence checks run at load time. `override_values` validates command structure independently of availability and is shared by persisted override normalization and `launch_commands.override_command`; the latter converts validation failures to LaunchError and retains executable/working-directory checks. Loading does not write sanitized source/launch configuration back automatically.

## Export boundary

`catalog_export.py` serializes canonical JSON and CSV without Qt. The main window selects visible rows in proxy order and presents file/error dialogs. The writer uses a same-directory temporary file, flush/fsync, close, then atomic replacement, with cleanup in finally. Existing symlink destinations are resolved and file permissions retained. Tests inject serialization, flush and replacement failures and verify previous contents remain intact. This protects against partial export writes; it does not promise directory-metadata durability after sudden power loss. The import format, CSV fields and canonical date representation remain unchanged.

The export file dialog's file-type filter chooses both the format (JSON or CSV) and the scope: all fields, names only, or names and dates. `export_catalog` validates a `scope` of `all`, `names` or `names_dates`. A names-only export writes `{"format": "magik-library-names-v1", "names": [...]}` for JSON or a single `title` column for CSV; a names-and-dates export writes `{"format": "magik-library-names-dates-v1", "games": [{"title", "date_added"}]}` for JSON or `title`/`date_added` CSV columns. Reduced scopes carry the visible rows' values in display order, do not mutate input rows and do not change the full-record `magik-library-v1` payload. `date_added` is the existing Date-added-to-library acquisition value and keeps its canonical representation, including null when unknown. Reduced JSON payloads are not importable saved libraries: the importer still requires supported store names on every game and rejects the file without changes.

## Store error wording

`error_messages.py` derives explanations and suggested actions from FetchError status/category rather than guessing from message text. Sync-worker errors and game-detail request failures use it while retaining provider isolation, severity and HTTP diagnostics. Unknown exception messages are not interpolated by this formatter. The transport still owns categories and retry behavior; presentation does not change authentication or request policy.

## Account-date report presentation

`acquisition_report_text.py` builds a Qt-free summary from the saved check counts, warnings and history-completeness flag. It distinguishes missing counters from zero and labels the result as a saved check rather than live database coverage. `report_dialogs.show_report` can display Summary, Technical details and Help tabs; other reports retain their existing single-page layout. Full date-report diagnostics remain available without mutating their input or starting a request.

## Game-detail report presentation

`metadata_report_text.py` groups saved results by store, provides human-readable outcome labels and explains retry actions. It does not calculate live database coverage or change retry policy. The report dialog uses the same outcome labels for technical entries, preserves all saved results including successes, and displays Summary, Technical details and Help tabs. Unknown outcomes remain visible as unrecognized rather than silently becoming success.

## Import and candidate sign-in validation

`catalog_import.py` normalizes and validates imported rows before the UI calls Database.save. It rejects malformed field types and unsupported stores for complete saved-library imports. Provider fetch normalization is unchanged. SQLite still supplies the write transaction; rejected imports do not reach it.

`session_verification.py` writes candidate cookies to a private TemporaryDirectory and runs the existing Steam/EA verification against that auth_dir. On success it atomically publishes only verified cookies to the real service file. No temporary token is promoted. `session_ui.CheckSession` owns the background call and reports a generic failure without exposing credentials. `web_sessions.renew_ea` binds cached tokens to a SHA-256 fingerprint of the normalized cookie records used by its WebsiteSession. Cookie changes or legacy caches without a fingerprint require renewal. A staged verification failure or failed atomic publication does not modify production sign-in files.

## Cover download retry boundary

`covers.py` owns QNetworkAccessManager downloads, bounded caches, unique temporary cache writes and a single parented retry-notification timer. `cover_retry.py` determines delays from attempt count, HTTP status and Retry-After. Deadlines use monotonic time; HTTP-date Retry-After is converted to a duration once. Very long waits are scheduled in Qt-safe timer intervals and rechecked before notification. Deadlines notify the UI once; only get_cover demand starts another request. Failure state survives retries until a successful download clears it. Missing, oversized and invalid images use a longer wait. `widgets.Covers` remains a compatibility import. Tests use a fake clock and mocked replies; no real cover downloads are required.

## Background catalog reads and imports

`catalog_loading.py` runs one CatalogRead at a time, coalesces further requests to the newest generation, and publishes only current results. Database.view_snapshot reads games, installation evidence and statuses in one transaction; catalog date backfill, installation decoration and facet collection happen in the worker. Main-window apply_catalog owns Qt model updates and restores selection and scrolling at application time. Closing suppresses publication and defers final window close until the read thread finishes. Initial status hydration merges current-session activity rather than replacing it.

`import_worker.py` reads and normalizes imports outside the UI thread, requests a store choice for provider-format JSON, and saves the complete validated batch. Database.save accepts an optional pre-commit guard; cancellation there rolls back all writes. Import outcome is consumed only after QThread finishes. The UI serializes imports against account operations and keeps browsing available. Tests use events and Qt heartbeat callbacks to prove that slow reads/normalization do not occupy the UI thread. qt_wait.settle adapts UI assertions to asynchronous completion.

Model reset/sort/filter application, reports, exports, schema initialization and small manual writes remain synchronous. Workers create their own SQLite connections; Qt models/widgets are never accessed from worker threads.

## Background exports and report preparation

`local_tasks.py` serializes exports and prepares report content in a QThread. `report_content.py` owns Qt-free text builders; `report_dialogs.py` owns widgets and retains existing public wrappers. Report tasks use Database.report_snapshot to fetch coherent raw records inside a read transaction, then decode and format outside it. The UI opens prepared dialogs only after the task thread finishes, and suppresses them if Stop was requested meanwhile.

`catalog_export.export_catalog` accepts an optional cancellation guard. It checks during JSON encoding/CSV rows and before atomic destination replacement. A published export is always reported as saved. Main-window local_active, import_active and the running account worker provide a shared busy check; tasks cannot overlap through the normal UI. Close requests cancel local tasks and retain thread ownership until completion. Existing visible-row ordering, literal report rendering and export formats remain unchanged.

## Live connection strip

`connection_checks.py` performs limited account probes with injected ConnectorIO transport and returns immutable ConnectionResult values. GOG authentication_headers and EA library_query are shared with library refreshes so connection checks do not implement a second auth flow. EA library_query also returns a getter for the current token so acquisition matching receives a renewed token after a 401 retry. Default library transport timeouts remain unchanged; probe transports supply shorter HTTP/helper limits.

`connection_status.py` owns the header widget, one periodic timer and a cancellable ConnectionChecks thread. Disabled/on-hold stores are never probed. Generations discard results after Sources changes. Busy/modal checks postpone new polling, and pause cancels pending stores while an in-flight request finishes. Server Retry-After delays suppress premature manual/periodic checks. Main-window close defers until both catalog reads and connection checks have finished. Badge tooltips and accessibility names describe the state without relying only on color.

## Unknown-value foreground styling

`unknown_style.py` supplies background-aware purple selection, a literal-text syntax highlighter, table/picker delegates and cover/combo text painting. Highlighter ranges count UTF-16 units so non-BMP characters before Unknown do not offset the formatting. Main details, raw text and reports use UnknownTextEdit; ColorLog attaches the same highlighter over its semantic formatting. Table foreground roles and the delegate preserve purple in selected cells. Styling does not mutate catalog data or exported/copied text.


Optional enrichment (v0.31): `extra_schema.py` owns fields, numeric bounds and
configuration keys without network/Qt dependencies. `extra_metadata.py` owns
the independent adapters (IGDB, ProtonDB, SteamGridDB, OpenCritic, HLTB) and the
background enrichment loop. It uses per-source retry state in local_state and
per-row provenance in raw.extra_metadata. `extra_source_ui.py` adds opt-in
settings tabs to Sources. The HLTB adapter needs no credentials: it obtains a
short-lived search token from howlongtobeat.com (the token is bound to one
User-Agent, shared by the init and search requests), refreshes it once on a
403, and converts the site's per-style times from seconds to hours. HLTB
columns are appended after all existing columns to preserve saved column
indexes.
Worker mode `extra` keeps HTTP and SQLite writes off the UI thread. Existing
account providers, Metacritic scoring, KDE identity and launch behavior are
unchanged. New fields/columns are appended to preserve saved column indexes.


Sign-in process isolation (v0.34): Sources imports `signin_process.ConnectSession`,
a controller with no Qt WebEngine imports. `session_browser.py` initializes the
child Qt application and invokes the existing embedded `session_ui.ConnectSession`.
A private request contains only service/auth_dir; the child publishes a bounded
non-secret success result. Session verification and atomic credential publication
stay in `session_verification.py`. Child crashes/exit errors become retry UI,
with optional child-only software rendering and X11 compatibility.

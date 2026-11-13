# Magik Games Library 0.42

A native Python/Qt catalog for CachyOS and KDE Plasma. Browse account libraries, collect metadata, detect existing installations and launch games through Steam, Heroic or Lutris. The app does not install or uninstall games, configure Wine/Proton, or manage game settings or saves.

## Date-first refresh, tidier toolbar and screen-safe window (0.42)

**Missing dates come first.** During a refresh, every Steam package mapping already saved in the 30-day cache is applied before any new request, so completed matches always fill in dates even when a later request is rate limited. New package lookups are ordered so licenses without explicit app IDs — the only evidence for those games' dates — are requested first while the request budget lasts. The saved date report now records how many lookups were postponed (`postponed_packages`) and whether the date pass finished (`date_fetch_incomplete`).

**Game details wait for dates.** If a refresh postponed date lookups (HTTP 429), the automatic "Get game details after refresh" step is skipped for that refresh and the activity log explains why. The next refresh retries the remaining mappings first; you can always run Get missing game details explicitly. Explicitly started metadata runs are never interrupted by this policy.

**Toolbar cleanup.** The main button rows now hold Sources…, Refresh libraries, the game-details checkbox, Get missing game details, Stop, and a Tools menu with the rarely used actions: Appearance…, Retry missing details, Fetch selected details…, Review metadata match…, Favorite / tags…, Copies across stores…, Get Metacritic data, Get extra game data, OpenCritic quota…, the three reports, Save/Delete preset and Backups…. Rescan installations and Installations… joined the second row, and the separate installations row is gone. Every moved action keeps its tooltip; the OpenCritic quota badge is now a menu entry so its changing text can no longer resize the window.

**The window never exceeds the screen.** Moving buttons into the menu cut the window's minimum width from about 2100 px to about 1190 px, and the counter line no longer carries its explanation sentence (it moved to a tooltip; "Metacritic" moved off the review-score label). On show, the window clamps itself to the screen's available geometry, so saved oversized geometry or a wider layout can no longer push it past the edges. Maximized and fullscreen windows are left alone.

Connection checks, refresh behavior, exports, reports and database formats are unchanged. Tests cover the fetch ordering, the details gate, the menu contents and the window clamp. Replace all app files and restart.

## Purple Unknown values (0.29)

Unknown values now use purple in table cells, game details, reports, source-data text, logs, filter pickers and cover-card details. The playtime filter also highlights its Unknown text. Purple shades adapt to the background, including light/dark themes and selected table rows.

Text highlighting preserves literal text, copy behavior, stored values, sorting and exports. Report/source text is still displayed as plain text; formatting does not interpret downloaded HTML. Tests check the foreground roles, selected rows, theme changes, Unicode positions and actual rendered purple glyphs. Replace all app files and restart.

## Live store connections (0.28)

The top-right status strip shows every store with a colored indicator: green for live account access, blue while checking, amber for setup/access/rate-limit issues, red for a failed check, and gray for disabled or unsupported stores. Hover over a store name or icon for the explanation and last-check time. Click the strip to check again. Rockstar remains on hold.

Enabled stores are checked on startup, after saving Sources and every five minutes while the app is idle. Checks pause for account/file tasks and open dialogs. Store-requested waiting periods are respected. Responses from an older configuration are discarded, and the window waits safely for an in-flight check during close. A current HTTP request may need to finish before closing.

Checks use the same account profiles and authentication as library refreshes. Steam checks account-library access without game details; GOG checks ownership access without its shelf/history queries; Epic reads its first library response; EA reads one library item and can renew its saved login. Amazon runs Nile library sync, which may update Nile’s cache. Checks do not write this app’s game library, fetch acquisition history, install games or launch anything. Existing sign-in helpers may update their own authentication files.

Normal probe requests use a 10-second transport timeout, while helper checks are limited to 45 seconds; existing EA session renewal retains its own timeout. The strip is a periodically checked status, not a guarantee that a connection remains available between checks. Connection tests use mocked services; live accounts must be verified on your machine. Replace all app files and restart.

## Background exports and reports (0.27)

JSON/CSV serialization and export writes now run in a background task. Export membership and order are captured from the visible list when you choose the file. You can keep browsing while it is saved. Stop is checked during encoding and immediately before atomic replacement, so a cancelled unfinished export keeps the previous destination file. A completed replacement is reported as saved even if Stop arrives afterward.

Installed games, Date added and Game details reports now read and format saved data in a background task. Only the report widgets are created on the main thread. Report data is read in one SQLite transaction, with decoding and formatting after releasing the read lock. Opening a report does not query store accounts. Stop suppresses unfinished reports and reports whose result was prepared just before the stop request.

A shared busy state prevents account operations, imports and these local tasks from overlapping. Closing during a task requests Stop and keeps the window open until it finishes, as with imports. Report text builders now live in Qt-free `report_content.py`; the existing report-dialog wrappers remain available.

Qt model updates, filtering/sorting, displaying report text and small manual edits remain on the main thread. Database and settings formats are unchanged. Replace all app files and restart.

## Background reloads and imports (0.26)

Saved-library reads, date backfill, installation matching and filter-option preparation now run in a background reader. Games, installation records and saved statuses are fetched in one SQLite read transaction. The UI keeps the previous view while reading, then applies the new model on the main thread. Repeated reload requests are combined; outdated results are discarded. Selection, filters and scroll positions are retained when possible, and initial saved-status restoration preserves activity already logged in the current session.

JSON file reading, validation and import writes also run in a background worker. Provider-format files still ask you to choose their store. Stop cancels before commit and rolls back pending writes; a completed commit is reported as saved even if Stop was clicked afterward. Imports and account operations do not run simultaneously. Browsing remains available while an import is processed.

Closing during a background catalog read waits for that read to finish and then closes automatically, without applying the pending result. Closing during an account operation or import retains the existing stop-and-wait behavior. Tests hold background workers deliberately while checking that Qt continues processing events, and cover coalescing, stale results, failures and rollback after SQL writes.

Qt model updates, sorting/filtering, reports, exports and small manual edits still run on the UI thread. This release addresses the repeated read/preparation work and file imports; it does not promise that every operation is asynchronous. Replace all app files and restart. Database and settings formats are unchanged.

## Cover download retries (0.25)

Cover downloads now recover from temporary failures without restarting the app. Connection errors wait 30 seconds, then longer after repeated failures, up to 15 minutes. Missing, invalid or oversized images wait six hours before another attempt. Server Retry-After delays are respected, including HTTP-date values.

An expired wait only notifies the interface; a new download starts when the selected game or visible cover grid requests that image. Background timers do not download off-screen covers. The four-download limit, 20-second transfer timeout, 8 MiB download limit and existing memory/disk cache bounds remain in place. Successful downloads clear their retry state.

Cover handling lives in `covers.py`, with the existing `widgets.Covers` import retained. Cache writes use unique temporary files and clean up after failures. A disk-write failure keeps the usable image in memory. Account data, game launching and credentials are unchanged. Replace all app files and restart.

## Import and sign-in safeguards (0.24)

Imports now validate the complete normalized batch before saving any rows. Invalid playtime, score, Boolean and text values produce an import error instead of reaching table rendering. Unknown store names in saved libraries are rejected rather than silently skipped. Valid JSON exports, manual dates and supported provider import formats remain usable. This does not repair malformed records already stored by older versions.

New Steam and EA sign-ins are checked in a private temporary folder. Verification requests, cookie rotation and temporary EA tokens stay there until the check succeeds. Only verified cookies replace the saved sign-in, using an atomic write. Failed checks and publication failures retain the previous saved cookies and token. Temporary verification files are removed afterward.

EA token caches now include a fingerprint of the cookies used to obtain them. A token from another sign-in is not reused. Previously cached tokens without a fingerprint renew once from the saved cookies; the verified temporary token is not copied into the production cache. This can add an automatic renewal request after connecting. Account endpoints and acquisition matching are unchanged.

Replace all app files and restart. Existing database and settings formats remain compatible. Cover-download retries and moving large database work off the UI thread remain separate follow-up work.

## Readable game details report (0.23)

The Game details report now has Summary, Technical details and Help tabs. Summary groups the most recent saved results by store and distinguishes details retrieved, partly retrieved, unavailable, failed and waiting requests. Unknown result types are kept separate instead of treated as success.

Help explains the result meanings, retry controls and the difference between missing details and missing ownership. Technical details include every saved result, including successful requests, with game titles, errors, last-attempt times and retry information. The report does not claim that a successful request fills every field or that the saved results cover the entire current library. Opening it does not contact stores or change data. Replace all app files and restart.

## Readable date report (0.22)

The Date added report opens on a plain-language Summary tab. Each store shows when it was checked, how many library entries matched a date, how many remained unmatched and what to check next. Missing counts are labeled Not reported, rather than treated as zero. Warnings and incomplete Steam license history are highlighted in the text.

Technical details retain the saved diagnostic fields in a separate tab; Help contains the store-specific instructions. The summary describes the last saved account-date check, not current database coverage: manual dates and previously saved dates can make the current library differ. Opening the report does not contact stores or change data. Replace all app files and restart.

## Actionable store errors (0.21)

Library refresh and game-detail errors now explain structured store responses in plain English. Rejected sign-ins show the relevant connection steps; access restrictions are distinguished from sign-in failures. Rate limits explain the wait, temporary failures suggest retrying later, and missing public game details are distinguished from an unavailable library service. Technical error text and HTTP codes remain available after the explanation.

Unexpected exception messages remain hidden because they may contain request details or credentials. Error categories, retry timing, account requests and saved-library behavior are unchanged. Replace all app files and restart.

## Clearer interface text (0.20)

Labels, connection instructions, installation help, date editing, status messages and reports now use plain English. “Game details” replaces “metadata” in everyday actions, and “Date added report” replaces “Acquisition report.” Help explains the difference between account ownership, installation status and launch readiness. Key actions and columns have tooltips explaining their scope and how Unknown values are handled.

Reports use labeled sections and include next steps and empty-state guidance. Technical source payloads and store errors remain available for troubleshooting. A Wine/Proton prefix is explained as a Windows environment folder. Manual-date help explains that a manual value, including Unknown, takes priority during refreshes.

Store IDs, internal status values, filter settings, saved data and account-query behavior remain unchanged. Replace all app files and restart.

## Export consolidation (0.19)

`catalog_export.py` now owns JSON and CSV serialization. Exports are written to a temporary file in the destination directory, flushed and closed, then atomically replace the destination. A serialization, disk-write or replacement failure leaves the previous export intact and removes the temporary file. New files are private by default; existing destination permissions and symlink targets are retained.

JSON keeps `magik-library-v1`, full records and canonical dates. CSV keeps the existing field order and escaping. Both keep the currently visible rows in display order. Export errors now also handle serialization failures through the normal error dialog. No library database, credential, acquisition or KDE changes are involved. Replace all app files and restart.

## Configuration consolidation (0.18)

`configuration.py` validates saved source options, installation links and per-game launch override structures. Wrong JSON shapes no longer break startup or source dialogs. Known text fields retain strings exactly, including credentials and paths; invalid values are omitted. Known switches require actual booleans, so text such as `"false"` cannot accidentally enable a provider. Unknown option keys remain available for compatibility, and Rockstar remains disabled.

Launch override structure validation is shared with command preparation. Invalid structures now produce LaunchError instead of unhandled type errors. Missing or unmounted executable paths remain editable; file availability is still checked only when saving launch setup or launching. Malformed saved override entries are ignored in memory; valid entries remain intact. Loading configuration does not rewrite the original options/launch settings.

No credential, database, settings-key or KDE identity migration is required. Replace all app files and restart.

## Background completion consolidation (0.17)

Completion messages and automatic scan policy now live in Qt-free `operation_policy.py`. Stopping a refresh no longer launches an installation scan afterward. A queued scan checks the completed worker's identity, cancellation state and window state before starting, so a newer operation or accepted window close supersedes it. The start action also refuses new work after an accepted close.

Non-cancelled refreshes retain their automatic scan, including refreshes with partial source failures. Existing saved data and failure summaries are preserved. Tests cover completion precedence, explicit stop requests and queued callback races. Replace all app files and restart.

## Browsing-state consolidation (0.16)

`browsing_state.py` validates persisted filters, sorting, view mode and presets before they reach Qt widgets. Malformed JSON shapes now recover with safe defaults instead of breaking startup. Valid facet selections, including values temporarily absent from the library, are retained; inputs are copied and duplicate facet values are removed. Sort indices and score thresholds are bounded to the existing UI ranges. Existing setting keys and formats remain unchanged.

The playtime picker uses the same canonical options as validation. Tests cover malformed settings across window restarts, valid preset roundtrips, literal flags, bounds and independent copies. Replace all app files and restart; library data and credentials are unchanged.

## Launch consolidation (0.15)

Launch dialogs remain in `launch_ui.py`; detached process handoff and logging now live in `launch_service.py`. `launch_commands.py` owns local override validation and the shared readiness rules used by selection and Play. Existing literal argument vectors, environment additions and working directories are preserved.

Launch activity carries explicit severity: failed launches now appear as errors instead of success messages. Successful handoff still does not claim the game is running. No database, settings, credentials or KDE identity changes are required. Replace all app files and restart.

## Transactional persistence consolidation (0.14)

Catalog normalization now lives in `catalog_data.py`; SQLite persistence lives in `storage.py`. `core.py` keeps the existing public imports available. All six normalization functions were structurally compared with the previous release and remain unchanged.

A source refresh now saves games, ownership reconciliation, acquisition diagnostics and successful/warning status in one SQLite transaction. Either every part commits or every part rolls back. A cancellation detected just before commit also rolls back the batch. The status and acquisition report share one refresh timestamp. Other readers continue to see the last committed snapshot until the new transaction commits.

Manual acquisition-date updates also move into storage, with a write lock acquired before reading the record. An edit made while a refresh is writing waits for the refresh, then updates the latest record instead of replacing it with a stale copy. Existing metadata and manual-date merge rules remain intact; clearing a manual date keeps the Manual override policy.

If a refresh save fails, the worker can still record a separate failure status after rollback; the previous game data and acquisition diagnostics remain available. Existing standalone metadata/report/status operations keep their public methods. There is no SQLite schema migration or account/settings reset. Replace all app files and restart.

## Provider separation and registry (0.13)

The third consolidation pass moves each store connector into its own module under `providers/`. Shared HTTP requests, helper subprocess handling and exception types move to `connector_io.py`. `connectors.py` remains the stable public interface, forwarding calls with an explicit transport dependency. Existing caller signatures, helper commands, request parameters and authentication behaviour remain intact.

`provider_registry.py` is the canonical provider order, source-field definitions and sync/launch/metadata capabilities. Source settings, background selection, metadata dispatch and launch controls now use that registry. Rockstar remains on hold, including when an old settings file says it is enabled. Its partial-library behaviour is also declared in the registry.

The extraction was checked structurally against the previous implementation: all 10 store functions match after undoing only transport injection, and shared transport/error bodies match. Regression tests also cover direct provider transport injection, late-bound public transport mocks, registry dispatch, stable source keys and disabled providers. No SQLite or settings migration is required; Steam coverage, acquisitions and KDE identity are preserved.

Replace the complete app files, including the new `providers` folder, then restart. See [ARCHITECTURE.md](ARCHITECTURE.md) for the consolidated boundaries.

## Structured results and activity log (0.12)

The second consolidation pass introduces Qt-free result contracts and a shared library refresh service. Provider diagnostics now travel with the batch rather than being hidden inside the first game. This also preserves acquisition reports when the owned-game list is empty. A compatibility adapter accepts the previous list format, validates store identity and removes legacy diagnostic fields before database writes.

Worker completion carries structured log entries with explicit information/success/warning/error levels. Metadata summaries choose severity from outcome counts, installation scans from actual states, and store refreshes from acquisition/shelf warnings or failures. A successful message mentioning “0 unknown” or “0 failed” therefore stays successful. Message text is escaped, remains copyable, and is never used to infer severity.

Activity history now survives table/filter/data reloads during the session, keeping up to 1,500 lines. Cancellation retains completed-source messages and saved data. Store status records gain an additive JSON severity field; no SQLite migration or settings reset is required. Old status records remain readable and display neutrally until their next refresh records an explicit level. On restart the most recent per-store statuses are restored; the full session log is not persisted.

Steam acquisition requests/matching, other store query protocols and KDE identity remain unchanged. Replace the complete app files and restart as usual. See [ARCHITECTURE.md](ARCHITECTURE.md) for the new contracts and service boundary.

## Consolidation and palette application (0.11)

The first refactor separates the entry point, main window, catalog model, source settings, reports, background worker, log renderer and shared identity/settings helpers. See [ARCHITECTURE.md](ARCHITECTURE.md) for module responsibilities, stable interfaces and test commands. Database format, saved settings keys, account connections and KDE identity remain compatible. Steam coverage and KDE pinning have been confirmed working by the user; their retrieval/association logic is retained.

Buttons now receive explicit action roles rather than being classified from their labels. Palette styles apply directly to widgets with stronger background colours; existing widget palettes also refresh when themes change. This replaces the previous dynamic-property stylesheet path that was not visually applying on the user's desktop. Automated tests compare rendered button pixels across all four palettes in System, Light and Dark modes. Native KDE rendering still needs confirmation on the user's machine.

Replace the complete application folder contents with this version: the entry point now imports the new modules. Launch normally; no database migration or KDE reinstall is required. Use Appearance… to switch palettes live.

## Appearance, columns and KDE fixes (0.10)

**Appearance…** opens live settings for the global app theme (System, Light or Dark) and four colour palettes: Ocean, Forest, Ember and Orchid. System follows the Qt/KDE palette without changing your desktop settings. Related buttons share a colour: refresh/connect/rescan, metadata/reports, filters/presets, import/export/file pickers, settings, play and destructive/stop actions. Disabled controls remain muted and keyboard focus stays visible. The selected theme and palette survive restart.

The bottom log uses readable theme-adjusted colours for successful operations, warnings, errors and informational messages, with coloured store labels. Messages remain selectable/copyable plain text and source text is escaped before rendering. Theme changes recolour existing messages. The display keeps the latest 1,500 lines; machine log files and stored diagnostics retain their original content.

**Columns…** is now a persistent dialog. Check or uncheck as many columns as needed, then Close. Each change takes effect and is saved immediately. Title stays visible.

KDE integration now uses an absolute installed icon path in the desktop entry and a matching application name, desktop file ID and window class. The human-readable display name is separate. Starting the app repairs its own user desktop entry and icon; it does not change Plasma's taskbar configuration. To clear an existing broken pin after replacing files:

```bash
cd ~/Apps/magik-games-library
bash install-kde.sh
```

Close the app, remove the old placeholder pin, launch **Magik Games Library** from KDE's application menu, then pin its running task again. The installed icon remains available when the window is closed. Keep the application folder at its permanent path. The installer and identity checks are tested locally; actual Plasma pin/group behaviour needs confirmation on your desktop.

## Steam license pagination correction (0.9.4)

The user's Firefox network capture confirmed **GET `/account/licenses/?continuationToken=…&offset=100`**. Version 0.9.3 used an incorrect POST endpoint and returned HTTP 405. That endpoint and its request method are removed.

The app now follows advancing continuation links from the license page using the saved Steam session. Each returned token and offset is used as provided by Steam, with English page formatting requested. Tokens stay out of reports. Only HTTPS links to Steam's account licenses path are followed. Earlier-page navigation is ignored; repeated content, account mismatches, failed requests and sign-in redirects reject the new date import while keeping the library and saved dates.

The report includes `license_pages` and `license_history_complete`. A full 100-row page without a recognised next link is explicitly marked incomplete and its verified matches are retained. HTML imports stay offline and also report possible truncation. Relative app/sub links supply explicit identifiers. Package lookup diagnostics from 0.9.3 remain available; packages without a public app mapping still remain unresolved unless independently matched by an exact app ID or unique exact title.

After updating, restart and Refresh libraries. Clear any Steam HTML import path to use the connected live session. Regression fixtures cover the captured GET URL, advancing tokens/offsets, multi-page parsing, failure handling and truncated pages. Authenticated coverage needs validation on the user's account.

## Visual library cues (0.9.2)

Installed titles have a green check beside their table title and an **Installed** badge over their cover. The marker follows installation scan results; incomplete, unknown and missing installations do not receive it. Installed does not necessarily mean launch setup is complete.

Each store has its own background tint in table rows and cover cards: Steam blue, GOG purple, Epic slate, Amazon orange, EA coral and Rockstar yellow. Tints adapt to light/dark palettes. Cover cards also have a store colour stripe; normal selection highlighting stays visible. Store names remain visible so colour is not the only identifier.

## KDE integration (0.9.1)

Extract the complete folder to its permanent location (for example `~/Apps/magik-games-library`), then run there:

```bash
bash install-kde.sh
```

No sudo is needed. Open **Magik Games Library** from KDE's application menu (Games), or search for it in KRunner. Right-click its running taskbar icon and choose **Pin to Task Manager**. The app includes a dedicated icon and desktop identity for window association on Wayland and X11. Existing Qt/KDE theme settings remain in use.

The menu entry points to this folder. After moving it, run setup again. Updating files in the same folder keeps the launcher valid. Close any older running copy before launching the new version.

Remove just the KDE menu entry and installed icon with `bash install-kde.sh --remove`. Unpin the taskbar entry separately. Your game database, settings and credentials are retained.

## New in 0.9 — readable dates and Amazon acquisition dates

Dates throughout the library, details and reports now read **16 Oct 2026** or **16 Oct 2026, 20:21:25**. Timestamps use your system timezone; calendar dates and month/year precision remain unchanged. Sorting still uses chronological values. Raw JSON, exports and stored values retain their original machine-readable dates. Manual acquisition dates use a calendar picker; uncheck Date known to clear a date.

Amazon acquisition dates now use **entitlementDateFromEpoch**, the millisecond timestamp on each account entitlement preserved by Nile. Existing cached records containing that field are backfilled when loaded; **Refresh libraries** retrieves updated entitlement data. Acquisition report shows coverage and invalid/missing values. Release, modification and sync dates are never substituted. Manual overrides remain intact. Live coverage depends on the entitlements returned by your account; absent or invalid dates remain Unknown.

Protocol reference: [Amazon GetEntitlementsV2 response](https://github.com/Lariaa/GameLauncherResearch/wiki/Amazon-Games).

## Added in 0.8 — EA renewal and Steam acquisition dates

Install the sign-in component on CachyOS / Arch, then restart the app:

```bash
sudo pacman -S --needed pyside6 qt6-webengine
```

With pip, install the full `PySide6` package from requirements rather than only PySide6 Essentials. Without WebEngine, existing browsing, manual EA tokens, launcher handoffs and Steam HTML imports still work; Connect displays the dependency command.

### One-time setup

1. **Sources → EA → Connect EA…** opens EA's official sign-in website inside a dedicated app window. Complete login and verification, then click **Use this session**. A background check obtains an access token from EA. Click **Save** in Sources. The automatic-renewal checkbox takes precedence over manual token / Lutris token-file inputs; those inputs are disabled while automatic renewal is selected. Connecting enables EA in Refresh libraries.
2. **Sources → Steam → Connect Steam dates…** opens Steam's official login. Sign in, including Steam Guard, then click **Use this session**. The check verifies dated licenses and uses that session's SteamID64 in Sources. Keep your existing API key: it still fetches the owned-game list. Click **Save** in Sources.
3. Click **Refresh libraries**. Date histories are fetched during library refresh; metadata retry and local installation scans do not fetch them.

The sign-in window has no password collector or password storage. Passwords are entered only into the website. It uses a private in-memory WebEngine profile, with only EA-domain or Steam-domain cookies retained by this app. It never reads Firefox's profile and does not change Lutris credentials. **Use this session** saves the scoped login locally. Cancel does not verify or activate the session. Connections become active in Sources settings only after Save.

### EA automatic renewal

The app stores an EA website session and a separate access token with its expiry under the app data directory's `auth` subfolder. Before fetching, reuse a token only if it has more than 90 seconds remaining; otherwise request a new one using the saved EA cookies. If the modern EA library API returns HTTP 401 or a recognized GraphQL authentication error, force renewal and retry once. Cookie rotation is persisted after requests. All network requests have timeouts; a rejected login produces a Connect EA instruction rather than an endless retry loop.

Renewal happens when a library refresh needs it, without a background timer or an open EA login window. EA can still invalidate the underlying login session; when that happens, sign in again. Select Remember me on EA's page if offered. The existing EA acquisition-history 404 is independent and is not fixed by login renewal.

### Steam date matching and limits

The website session is separate from the Steam API key. SteamLoginSecure identifies the signed-in account and must match the SteamID64 used for the owned-game query. A mismatch rejects the date import while retaining the library. Steam licenses are fetched with English date formatting and parsed without executing their page actions.

Dates match explicit app IDs and package IDs when the page exposes them. Package-to-app mappings use Steam's read-only package-details API and are cached for 30 days. Unique exact license-title matches are also accepted after whitespace/case and trademark normalization; this is recorded in **Date added source**. No fuzzy name matching is performed. Duplicate catalog titles, renamed games and bundles without resolvable IDs can remain Unknown. The report lists matching methods, ambiguous rows, unavailable mappings and unmatched games.

Package mappings describe current package contents; the date is the package license date, which need not be the exact date a later-added app entered a package. Check provenance and use a manual date where historical precision matters. First-time package resolution may take several minutes for a large library. It is paced, cancellable and cached. HTTP 429 stops further package requests for that refresh while retaining completed and exact-title matches. Existing dates and manual overrides are preserved if a date source fails.

If embedded Steam sign-in is blocked, open this link in Firefox while signed in:

<https://store.steampowered.com/account/licenses/?l=english>

Save it as an HTML file (Ctrl+S, HTML only), then select it under **Sources → Steam → License HTML import**. This file takes precedence over the saved website session; clear it to return to live fetching. An identifiable account mismatch is rejected. Importing an HTML page without an embedded account ID relies on the user selecting their own page. No Firefox cookies need to be exported. Connect Steam dates clears an old HTML override after successful connection.

### Session storage and disconnect

App-owned cookie/token files are stored locally as JSON with mode 0600 inside an auth directory with mode 0700, normally `~/.local/share/magik-games-library/auth`. They are not encrypted; treat them like credentials, as with the manual tokens already saved by this app. Cookies and tokens are excluded from catalog exports and diagnostic reports. **Forget saved session** immediately deletes that service's cookie/token files and turns off its Sources checkbox; it does not sign out Firefox or revoke the server session. Existing library data remains available.

### Validation

124 automated tests pass, including expiry handling, cookie rotation, domain filtering, bounded 401 retries, Steam account mismatches, HTML parsing, explicit IDs, package caching, exact-name ambiguity and manual-date preservation. A real WebEngine dialog was exercised offline through cookie capture, a mocked verification worker, acceptance and cleanup. Sources controls were tested, and dialogs were inspected visually. No private account credentials were available for live EA/Steam authentication tests; the one-time sign-ins on the user's system are required to validate service acceptance and actual date coverage.

## Changes in 0.7.3

The EA access-token and Steam API-key fields have a trailing eye icon. Click to reveal the value; click again to mask it. The tooltip changes between Show value and Hide value. Each newly opened Sources dialog starts masked. Toggling preserves the field value and selection and does not change saved credentials or authentication behavior.

## Changes in 0.7.2

Epic's account-validated 707/707 acquisition matching path is unchanged.

EA now tries the consolidated-entitlements request on `api2.origin.com`, an existing client implementation's route, rather than starting with the route that returned 404 on `api1`. The identity request and token remain the same. If api2 returns 404/410, try api1 once; authentication errors, rate limits, timeouts and other failures do not trigger cross-host retries. The report records the route attempts. This is an alternative route, not a confirmed replacement for every account; authenticated date coverage remains to be tested on the user's system.

GOG date coverage is unchanged in this release. Diagnostics now distinguish unmatched records with an account-shelf entry from owned-ID-only records, and distinguish products absent from order history from products seen but ineligible. Up to 50 unmatched ID/title samples prioritize shelf entries; excluded orders/refunds/missing dates have explicit reasons. A small sample of order product IDs outside the owned library helps investigate bundle/edition differences. No dates are inferred by title or assigned to bundles' presumed contents. Receipt IDs, prices, gift-recipient addresses and raw order history are not persisted in diagnostics.

Protocol reference for the alternative EA read-only entitlement route: [Origin client request implementation](https://gist.github.com/BlackSwanBay/7c37d20f86ce21396ab0a0378cdbb16b). Only the account-entitlements GET protocol was consulted; no download, activation or other client actions are included.

## Fixes in 0.7.1

The user's acquisition report confirmed that GOG order history succeeds but labels completed purchases with `status: "purchase"`. The previous filter rejected that status. These orders are now included; `gift_by_me` remains excluded, along with refunded products and gifts sent to someone else.

Epic now queries the paginated library-items service using the same Legendary session. Its explicit `acquisitionDate` is matched by **namespace + appName**, or namespace + catalogItemId, and takes precedence over exact entitlement grant-date fallback. This avoids the entitlement audience/executable product mismatch without namespace-only guessing. The report adds library query success/failure, record counts, dated records and library-date match counts. Failed or incomplete pages are not partially applied. Existing manual dates remain authoritative.

EA acquisition errors now identify whether the identity endpoint or legacy consolidated-entitlements endpoint failed. The legacy EA acquisition source remains unresolved when it returns 404; the successful modern library query is retained. Steam and Amazon acquisition history support is unchanged.

Refresh libraries after updating. The GOG regression and Epic library pagination/matching are tested using fixtures; account coverage still needs validation on the user's machine.

## New in 0.7: acquisition queries and diagnostics

**Refresh libraries** now attempts separate, read-only acquisition queries after successful Epic/GOG/EA library retrieval. **Acquisition report…** displays the last results per store, warnings, record counts, exact match counts and up to 30 unmatched Epic product identifiers. Reports persist locally and contain no tokens, account IDs, prices or receipts. These additional queries do not run during ordinary metadata retries or local installation scans.

- Epic: use the refreshed session from the **same** Legendary profile to retrieve all entitlement pages. If access fails, use that profile's entitlement cache. Match namespace plus catalog item ID, then namespace plus metadata entitlement name. Do not match by namespace alone or use product creation dates. Report cache/live record counts and both match methods. This addresses the missing entitlement-name match in 0.6.1; account coverage still requires validation.
- EA: reuse the EA token to obtain the account PID in memory, then request consolidated entitlements with the vendor JSON accept header and `authtoken`. Match grant dates by offer ID. This optional legacy endpoint can reject a token that works with the modern GraphQL library; failure is reported and the library is retained.
- GOG: try paginated completed-order history using existing bearer authentication. Some accounts/endpoints require a separate website session and may return 401/403 or HTML. Such failures are explicit and leave the library usable. Only exact product IDs in completed/redeemed orders are used; refunded products and gifts sent to someone else are skipped. The order-status counts help diagnose unsupported responses. This is an order date and can differ from a redeemed gift's acquisition date.
- Steam: the current API-key source still has no acquisition-history integration. Website license history requires additional authentication and packages may contain multiple apps. It is not silently guessed from release dates or filesystem times.
- Amazon: Nile account entitlements supply `entitlementDateFromEpoch` acquisition dates as of 0.9. Missing or invalid values remain Unknown.

The new requests can add refresh time and have cancellation checks between pages. Source errors are optional and never erase a previously stored date. User-entered dates always take precedence. Mock tests validate matching, pagination, fallback and failure behavior; authenticated coverage cannot be validated without your account data.

Protocol references: [Legendary API and cache](https://github.com/legendary-gl/legendary), [Purchase Date Importer services](https://github.com/darklinkpower/PlayniteExtensionsCollection/tree/master/source/Generic/PurchaseDateImporter/Services). Third-party code is not bundled.

## Fix in 0.6.1: Epic acquisition dates

Version 0.6 only inspected library responses for date fields and did not read Legendary's separate entitlement cache. Epic refresh now reads `entitlements.json` from the same Legendary profile used for the successful account query. It matches **namespace plus catalog item ID**, never just namespace or game title, and uses the earliest active, nonconsumable matching grant date. Product creation/release dates are never used. Missing/corrupt entitlement caches leave dates Unknown and produce a progress diagnostic; library import still succeeds. No additional credentials or network endpoints are used. Refresh libraries to populate dates; metadata retry does not fetch them.

Refresh summaries now say how many acquisition dates the source returned. This is not a universal purchase-history importer: Steam, GOG, Amazon and EA can remain Unknown with the current sources. Manual dates continue to take precedence.

## New in 0.6

Wine/Proton prefixes are discovered automatically in every registered Steam library's `steamapps/compatdata`, `~/Games` (two levels), `~/.wine`, and ancestors of Lutris installation paths. Native and Flatpak Steam library registrations are followed. Symlinked candidates are deduplicated; discovery does not recursively scan home or all mounted drives. Each directory level is bounded to 2,048 candidate directories, and cancellation is supported. Prefix paths appear in Installation report even when no Epic/EA game registration is present. Keep using Windows prefixes settings for unusual locations; no files in launchers or prefixes are changed.

**Date added to library** and **Date added source** are new sortable columns, included in game details and JSON/CSV exports. They mean acquisition into the store account, not release date, installation date or initial import into this app. Explicit `datePurchased`, `purchaseDate`, `acquisitionDate` or `grantDate` values on account records are normalized when available. Cached account payloads are checked too. The current Steam owned-games response does not supply this date; many other helper responses also omit it, so Unknown is expected. No additional account-history permissions or purchase-history requests are made.

Right-click a game → **Set date added to library…** to enter a calendar date manually. Manual dates survive account refresh and enrichment. Leaving the value blank records an explicit Unknown. Dates do not fall back to the first refresh timestamp. Existing database records, settings, links and launch commands are preserved.

## Fixes in 0.5.1

Steam libraries are rescanned from their current manifests even when Linux device numbers changed since the previous scan. Old snapshots recover automatically; do not delete your database. Missing libraries and retained sources now produce explicit warnings with paths. Scan summaries separate installed, incomplete, unavailable, missing-file and unknown registrations; installed no longer means launch-ready. Counts include manager tools and runtimes as well as games.

## Update from an earlier version

Close the app and replace its program files with this release. Keep your existing local database and settings. No database reset is needed.

1. Launch the app. A local installation scan starts automatically, without querying your accounts.
2. Select a detected game and click **Play**, double-click it, or use its right-click menu. Multiple launch entries produce a provider chooser.
3. Filter **Installed status → Installed** to show ready registrations only.
4. Use **Installations…** for nonstandard data roots or launcher executable paths, and **Installation report…** to diagnose missing matches.
5. Use **Link installation…** if a game is installed in Lutris but its service ID does not match the account record.

The prior multi-select filters, presets, cover cache, metadata cooldowns and plaintext Steam/EA settings are retained. Rockstar remains on hold.

## Run on CachyOS / Arch

```bash
sudo pacman -S python-pyside6
```

Open a terminal in the extracted `magik-games-library` directory:

```bash
bash run.sh
```

Alternatively use an isolated environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Python 3.10+ and PySide6 6.7+ are required. The backend otherwise uses the Python standard library. Qt follows your desktop's available style.

## Browsing

- **Multi-select Stores, Types, Genres, Platforms, Languages and Installed status:** click a picker, search its values and tick those you want. Selected values match with OR within that picker. Different pickers combine with AND. No selection means no restriction.
- **Unknown values:** each picker includes `(Unknown)` when relevant. Unknown playtime is never classified as unplayed.
- **Search:** all entered words must appear somewhere in title, store ID, developer, publisher, genres or description.
- **Other filters:** played/unplayed/unknown playtime, minimum Metacritic, and inclusion in the latest successful library query.
- **Presets:** Save preset (in the Tools menu) stores filters, sort field/direction and view mode under a name. Apply preset restores them; Delete preset (Tools menu) removes the selected preset. Saving an existing name asks before replacement. Credentials are not included in presets.
- **Columns:** show/hide columns using Columns. The title column stays available. Column visibility, order and widths persist across restarts.
- **Sorting:** click table headers or use Sort by and Descending. Sorting also applies to the cover grid.
- **Covers:** the table and cover grid share filtering, sorting and selection. A card shows artwork, title, store, type and installation status. Missing artwork receives a labelled placeholder. Selecting a game displays Details and Original metadata in the side panel.
- **Cover cache:** only images requested for visible cards or selected details are loaded, with at most four concurrent transfers. Images are saved locally for offline reuse. An in-memory cache holds 160 scaled covers; a disk cache is periodically pruned toward 256 MiB. Failed images retry after restarting. Cache contents are regenerated as needed.
- **Restore:** the last browsing filters, sort and view mode are restored at startup.
- **Export:** writes currently visible records, in sorted order, as JSON with original metadata or flat CSV. The file dialog's type list also offers reduced variants: names only (a `names` list in JSON, a single `title` column in CSV) or names and dates (each title paired with its Date added to library value — the acquisition/purchase date recorded for the store account, empty when unknown; `title`/`date_added` columns in CSV). This applies equally to table and cover views.
- **Import JSON:** accepts this app's exports, Legendary/Nile arrays, or generic records with stable `id` and `title`. Imports merge; they do not reconcile ownership.
- **Tools menu:** less frequently used actions live behind the Tools button: Appearance…, Retry missing details, selected-game actions, extra metadata runs and OpenCritic quota, the three reports, Save/Delete preset and Backups…. The main rows keep Sources…, Refresh libraries, Get missing game details, Stop, the preset dropdown, Apply preset, Columns…, Export…, Import JSON…, Rescan installations and Installations….
- **Window size:** the window clamps itself to the screen on show; refreshing, renaming buttons or quota badges cannot push it beyond the visible area.

Filter values are lightly normalized: game types and common OS aliases are unified; language markup is removed and some language codes/names are normalized. Genre names/tags come from the providers and are not a universal taxonomy. Compound names and languages can still differ across stores.

## Metadata fetching and retries

**Refresh libraries** queries enabled account sources and can enrich afterward. **Fetch missing metadata** considers all current cached Steam/GOG/Epic records needing extra metadata; it skips completed responses and respects retry dates.

| Latest outcome | Normal retry interval |
|---|---|
| Unavailable public page / HTTP 404 or 410 | 7 days |
| Partial metadata with an extended-endpoint 404 | 7 days |
| Other failure or partial result | 1 hour |
| Deferred because the provider was paused | 15 minutes |

Retry dates also apply to results recorded by earlier app versions. They are checked when you start a metadata run; the app does not schedule background runs. **Retry unavailable** overrides these cooldowns for all missing metadata, including partial and failed records. It still skips completed enrichment and retains per-request pacing/backoff.

Requests are paced at 2.5 seconds per game, plus request/retry time. Temporary main-request errors retry up to twice with interruptible delays. Persistent rate limits, HTTP 401/403, or three consecutive other errors pause that provider for the current run while other providers continue. Several hundred games can take 30 minutes or longer.

**Metadata report** shows each incomplete game's last result, reason, timestamp and next retry date. Select and copy its text to report a problem. A successful enrichment response does not mean every field was provided. Missing values remain Unknown. Store scores are not silently converted into Metacritic scores.

Completed library queries and individual enriched games are saved as they finish. Stop preserves completed work; it can wait up to the current network timeout. Closing during an active operation asks you to let it stop first.


## Installation detection and Play — new in 0.4

### What is supported

| Provider | Detection | Launch handoff |
|---|---|---|
| Steam native / Flatpak | Registered library folders and app manifests | `steam -applaunch APPID` or the Steam Flatpak equivalent |
| Heroic native / AppImage / Flatpak | Epic/Legendary, GOG and Nile installed registries under Heroic's data root | Heroic's `heroic://launch?appName=ID&runner=...` protocol |
| Lutris native / Flatpak | Read-only `pga.db` query for installed entries, matched using service IDs | `lutris lutris:rungameid/ID` or the Lutris Flatpak equivalent |

The provider owns its Wine/Proton selection, prefix, launch options, working directory and normal pre-launch behavior. Our Play action does not replace those settings. The provider may perform its usual updates, authentication or save syncing as part of launching, according to your existing configuration.

### Windows prefixes and game launch setup — new in 0.5

In **Installations… → Windows prefixes**, optionally enter additional Wine prefix or Proton compatibility folders, one per line. Common locations are now discovered automatically. Both `drive_c` and `pfx/drive_c` layouts work. For example, add the existing Steam compatibility directory containing your Epic launcher, or `~/Games/ea-app`. No entire-home scan is performed.

Epic detection reads `.item` files in `C:/ProgramData/Epic/EpicGamesLauncher/Data/Manifests`, matches AppName exactly, follows Windows drive mappings through `dosdevices`, and respects the incomplete-install flag. EA detection reads `*/__Installer/installerdata.xml` below `C:/Program Files/EA Games` and `C:/Program Files/Origin Games`. Add other EA library folders as Linux paths in the same settings tab. EA content IDs are matched to catalog IDs/known aliases; use **Link installation…** if the account offer ID differs. Existing Lutris registrations can still be linked there too. EA evidence confirms installer registration and an existing directory; it does not verify every game file or an interrupted download.

Detected prefix games require **Launch setup…** before Play is available. Choose an executable script or launcher helper that already starts that particular game with the correct runtime, prefix and launcher. The app does not guess Wine/Proton invocations. Arguments use a JSON array, for example `["argument with spaces", "another argument"]`. Environment additions use a JSON object, for example `{"WINEPREFIX": "/home/toto/Games/ea-app"}`. These are literal values: `~`, `$HOME`, pipes and shell substitutions in arguments are not expanded. A shell script must have a shebang and executable permission. An optional working directory is supported.

Overrides apply to the selected catalog game across its detected installations; configure your script for the intended installation. The installation record is checked again before every launch, including when an override is used. Leave the executable blank and Save to remove an override. Overrides and manual links are saved locally in app settings, separate from account exports, and are never taken from imported JSON. They can also override a Steam/Heroic/Lutris handoff. Successful process handoff still does not prove the game started.

Standalone Legendary/Nile installations outside Heroic are not detected automatically. Rockstar remains on hold.

### Status meanings

| Status | Meaning |
|---|---|
| Installed | A supported manager records an installation, its path exists, and no recognized incomplete flag applies. This is not a full file-integrity check. |
| Incomplete | Steam or Heroic reports an incomplete install; Play is disabled. |
| Unavailable location | A registered library/drive or previously scanned source is unavailable. Prior evidence is retained. |
| Not detected | No matching ready registration was found in the scanned managers, or a stale record has missing files on accessible storage. This is not proof of global uninstallation. |
| Unknown | No relevant provider was scanned, the installation path is absent/relative, or source data is unreadable. DLC without its own registration also remains Unknown. |

For a game with several entries, a ready installation takes precedence in the summary; details show every matching entry. Play offers only entries marked Installed. The path and provider are also available as sortable columns and in Details.

Installation matching uses store IDs. No title-based matching or arbitrary folder-name detection is performed. The scanner decorates your existing account catalog; registrations not in that catalog remain visible in Installation report rather than being added as owned games automatically. Imported catalog files never supply executable launch instructions.

### Locations and configuration

The scanner checks native Steam client roots (`~/.local/share/Steam`, `~/.steam/steam`, `~/.steam/root`) and Steam Flatpak data roots, follows Steam's registered game libraries, and reads `appmanifest_*.acf`. It checks both modern and older library-folder metadata. Fully installed requires Steam's installed state flag and an existing game path.

For Heroic, it checks native and Flatpak config roots (plus an explicitly configured Heroic metadata root):

- `legendaryConfig/legendary/installed.json` for Epic.
- `gog_store/installed.json` for GOG.
- `nile_config/nile/installed.json` for Amazon.

For Lutris, it checks `pga.db` in the native `~/.local/share/lutris` or Flatpak data folder. The installed flag plus a directory or absolute executable path is required. Lutris entries without an exact service-ID match can be associated manually with a selected catalog game. Choose a game-specific Lutris entry, not a generic EA/Epic launcher tile: the provider launches exactly what that entry configures. This association is stored in this app's settings and does not edit Lutris.

**Installations…** accepts additional provider data roots, one per line. Enter a Steam client root, Heroic configuration root, or Lutris data root—not an arbitrary game folder. Standard native/Flatpak locations are still scanned. Custom native executable/AppImage paths can be selected there. Paths containing spaces are supported.

For a genuinely nonstandard provider profile/data root, configure a matching launcher wrapper executable that selects that profile. The app refuses to silently hand a custom profile's game ID to the default profile. The wrapper receives the same fixed game arguments as the standard launcher. An ordinary AppImage using Heroic's standard root only needs its executable path, not a custom wrapper.

The app resolves native launchers through PATH or your configured executable; Flatpak registrations use the corresponding application ID and verify that it is installed before handoff. It does not register or repair desktop protocol handlers.

### Scanning, launching and diagnostics

Scans run in a worker at startup, after account-library refresh, when you save Installations settings, or on **Rescan installations**. They do not query accounts or execute games. Cancelling a scan keeps the previous snapshot.

Before Play, the app rechecks the path and registration. A changed/removed registration requires rescanning. The process is launched without a shell and detached so closing the catalog does not kill the game. A successful handoff means the launcher process was started; it does not establish that the game reached a running state. Provider-side startup problems must be checked in that provider's logs.

The status panel and local `launch.log` record handoffs and immediate failures. The log rotates at roughly 1 MiB. **Installation report** lists registrations, locations, states and source-read warnings. Installation evidence is kept in a separate database snapshot and never changes account ownership or metadata-query history.

## Accounts and authentication

Steam keys and manually entered EA tokens are saved in plain text in Qt settings, normally `~/.config/Magik/GamesLibrary.conf` on Linux. `$XDG_CONFIG_HOME` is respected. Clear a field and Save to forget it. Source paths, enabled accounts, view settings and presets are saved there too. Persisting an EA token does not extend its expiry: renew it if EA rejects it.

Authentication JSON selected for GOG/EA is read locally. GOG refresh tokens are refreshed only in memory; its source file is not rewritten. Legendary/Nile may refresh their own account/library caches. No game management commands are invoked.

### Steam

Obtain your own key from https://steamcommunity.com/dev/apikey. Enter it and your SteamID64 or profile vanity name, then enable Steam. Full profile URLs and account login/display names are not accepted as vanity names. Game Details privacy may need to allow access. Inaccessible responses are reported as failures rather than treated as empty libraries.

The owned-games endpoint supplies account games, playtime and last-played values where returned. Public store details add descriptions, genres, developers/publishers, dates, languages, OS support, controller support, Metacritic and art where available. Public pages are unavailable for some removed, restricted, test or auxiliary apps. The endpoint may not reproduce every Steam license/shared-game category.

### GOG

Sign into GOG in Heroic and select its `gog_store/auth.json`:

- Native: `~/.config/heroic/gog_store/auth.json`
- Flatpak: `~/.var/app/com.heroicgameslauncher.hgl/config/heroic/gog_store/auth.json`

GOGDL files containing `access_token`/`refresh_token` within a client-ID object are also supported.

Version 0.3 combines the owned-ID endpoint with paginated **authenticated account shelf** queries, including visible/hidden games and movies. The shelf can provide titles and basic metadata even when a public product endpoint returns 404. Owned-ID results are retained if the optional shelf fails, and the status line reports incomplete shelf access. Shelf entries may increase the record count by exposing additional owned items. Neither route is guaranteed to expose a human title for every ID.

Public product/v2 endpoints add richer information. Data is preserved in Original metadata, including requirements and other fields not yet represented by columns. Account shelf pagination/recovery was tested with mocks, not a live private account; validate its reported results on your machine.

### Epic

Use Legendary's existing session. If needed, install Legendary with pipx:

```bash
sudo pacman -S --needed python-pipx
pipx install legendary-gl
~/.local/bin/legendary auth
```

Set executable `/home/YOUR_USER/.local/bin/legendary` if it is not on your app's PATH. Leave its config directory blank for a standalone Legendary setup. To reuse Heroic's session, select its bundled executable and the Legendary directory containing `user.json`, commonly `legendaryConfig/legendary` under Heroic's config root. Do not use session import flags unless you intend their effect on the original launcher's session.

The app queries `legendary list --json --include-non-installable --force-refresh`, retaining third-party titles and attached owned DLC.

Extra Epic metadata uses Heroic's read-only `store_cache/legendary_gameinfo.json` when available, followed by public Epic content queries and a GraphQL fallback. The optional Heroic metadata root defaults to native and Flatpak locations. Heroic itself is not required. Exact Epic namespaces are used; there is no title guessing. Descriptions, developer/publisher, tags, dates, OS support, languages and art are mapped when returned; requirements remain available in Original metadata. GraphQL fallback has narrower coverage. DLC sharing a parent's namespace is not assigned the parent's product details.

Live checks in the previous release succeeded for A Short Hike's namespace mapping and content response. GraphQL fallback and cache/error behavior were tested using mocks. Broad coverage still requires validation on your actual library.

### Amazon

Use Nile's existing standalone or Heroic session. The upstream v1.2.0 Python packaging can fail during pipx installation; the standalone Linux x86_64 release is an alternative:

```bash
mkdir -p ~/.local/bin
curl -fL https://github.com/imLinguin/nile/releases/download/v1.2.0/nile_linux_x86_64 -o ~/.local/bin/nile
chmod +x ~/.local/bin/nile
~/.local/bin/nile auth --login
```

Select `~/.local/bin/nile` as the executable. For a standalone login leave config root blank. When reusing Heroic, the config root is the **parent** of Nile's `nile` directory; Nile appends `/nile` to `NILE_CONFIG_PATH`. Heroic commonly uses `nile_config`.

The app invokes only `nile library sync` and `nile library list --json`. This covers titles delivered through Amazon Games, not unclaimed Prime offers or Luna. Games redeemed on GOG/Epic appear in those libraries.

### EA

Enter an EA access token directly, or select Lutris's JSON token file (the entered token overrides the file):

- Native Lutris: `~/.cache/lutris/ea_app/auth_token`
- Flatpak: `~/.var/app/net.lutris.Lutris/cache/lutris/ea_app/auth_token`

Some Lutris releases require installation of the Windows launcher before offering their account login. This catalog does not perform that installation. An alternative that can work with an existing Firefox EA session is: sign into https://www.ea.com/, then visit the token URL below in the same browser profile and copy only the `access_token` value if returned:

https://accounts.ea.com/connect/auth?client_id=ORIGIN_JS_SDK&response_type=token&redirect_uri=nucleus%3Arest&prompt=none

The route can fail if EA does not recognize that browser session. EA querying is experimental and tokens expire; no automatic EA token refresh is implemented. The app requests paginated PC full-game entitlements and product titles/art, not a complete EA Play catalog or DLC inventory.

### Rockstar — on hold

Rockstar refresh is disabled in 0.3. Existing cached records and source path are retained. The earlier log-based recovery code remains for future work, but no Rockstar query runs from the UI even if older settings enabled it.

## Storage and architecture

- Database: `$XDG_DATA_HOME/magik-games-library/library.sqlite3`, default `~/.local/share/magik-games-library/library.sqlite3`.
- Covers: `covers/` beside that database; regenerated on demand.
- One record per store ID, so a game owned in two stores has two records. Cross-store deduplication and edition matching are not implemented.
- Successful complete library queries mark absent prior records inactive instead of deleting them. Absence is not proof of license revocation. Failed account queries preserve previous active flags and metadata.
- Only one current account per store is supported. Switching credentials reconciles that store to the new account after a successful query.
- Original game/product responses are retained and common credential keys are redacted. Account credentials are not included in catalog exports. Exported metadata can include provider links and other game information.

Modules: `core.py` stores/normalizes records, `connectors.py` queries account and Steam/GOG product APIs, `epic_metadata.py` handles Epic extras, `enrichment.py` handles metadata scheduling, `browsing.py` matches facets, `widgets.py` supplies pickers/cached artwork, `installations.py` reads provider registrations and builds launch arguments, `launch_ui.py` provides launch/configuration UI, and `app.py` hosts the Qt UI and worker.

## Validation

```bash
python3 -m unittest discover -s tests -v
```

124 tests cover this release: backend normalization and persistence, authentication-response handling, pagination, GOG title recovery/fallback, retry schedules and manual override, Epic cache/API behavior, OR/AND facets, unknown playtime, presets, restart persistence of EA/Steam values using dummy credentials, column visibility, shared selection and offline artwork reuse. PySide6-dependent tests skip if the binding is absent. Table/grid rendering was additionally inspected offscreen. The added tests cover installation formats, unavailable drives, partial installs, registry changes, read-only Lutris queries, launch arguments, manual associations, old column-layout migration and mocked launch handoff. Qt detached launch was also checked with `/usr/bin/true`; no actual game was launched in validation. Authenticated account APIs were tested with mocks; no private credentials are bundled or used in tests.

Protocol references include Steamworks documentation, Legendary and Nile, Heroic's GOG/Epic implementations, Minigalaxy/gogrepo account-shelf usage, and Lutris's EA service. Third-party launcher code is not bundled.


### Direct Metacritic data (v0.30)

Choose **Get Metacritic data** to check active library titles in the background.
The existing Metacritic column and minimum-score filter use the verified PC
critic score when available. Store-supplied scores remain the fallback.
Additional optional columns show PC user score (out of 10), critic/user review
counts, verdict, age rating, genre, PC release date, source URL, last check and
match status. Enable them with **Columns…**; they are also included in exports
and game details. Unknown values remain unknown.

This reads public game-page data, without a private API key or website session.
Titles are converted to candidate page names, then checked against the returned
title and explicit PC platform. Trademarks and punctuation are normalized;
edition words are preserved. Known release years differing by more than one
year are rejected. Alternate slugs, renamed titles and uncertain editions need
a future manual matching workflow; they are not silently matched to another
game. The website search endpoint is not automated.

Requests are sequential with a three-second pause. Successful checks are cached
for seven days, failures for one day. Access refusals and rate limits stop the
run and pause further requests for a day. Stop preserves results already saved.
Existing verified scores take priority during subsequent store refreshes. Failed
checks preserve previous values. Website changes may require parser updates.
No complete review texts, quotes or screenshots are collected. Metacritic
fields remain separate from store genres, descriptions and release dates.


### Four optional enrichment sources (v0.31)

Open **Sources…** and configure the new IGDB, ProtonDB, SteamGridDB and
OpenCritic tabs. Then choose **Get extra game data**. These requests run
separately from account refreshes, and never install or launch a game. Each
source can be disabled independently. Enable the new columns with **Columns…**;
all fields are also shown in game details and saved in JSON/CSV exports.

| Source | Setup | Added information |
| --- | --- | --- |
| IGDB | Twitch developer Client ID + Client Secret; https://api-docs.igdb.com/ | User/critic ratings, genres, themes, modes, perspectives, franchises, summary, cover and PC local-player/co-op counts when provided |
| ProtonDB | No credentials; https://www.protondb.com/ | Linux tier, recent tier, confidence and community report count |
| SteamGridDB | Personal API key; https://www.steamgriddb.com/profile/preferences/api | Cover, banner, logo and icon URLs, artist names and per-image attribution |
| OpenCritic | RapidAPI key and an OpenCritic API subscription; https://rapidapi.com/opencritic-opencritic-default/api/opencritic-api | Average top critic score, percentage recommended, tier and review count |

IGDB access tokens are obtained automatically and renewed on expiry or one
authorization rejection. Client credentials remain in local settings, masked
until revealed; no keys or access tokens are written to game records/exports.
OpenCritic plan quotas and any charges are controlled by your RapidAPI plan.
The app never purchases or changes a subscription.

Matching uses a unique exact normalized title, retaining edition words and
rejecting conflicting known release years. IGDB additionally requires a PC
entry. ProtonDB always uses an exact Steam app ID: directly for Steam games,
or through a verified IGDB external mapping for another store. It never uses
a title-only compatibility guess. SteamGridDB also prefers this Steam ID,
using exact title matching when none is available. Artist credits and asset
IDs remain in the entry's saved source data. Static artwork flagged as NSFW,
humor or flashing is excluded. Existing covers are kept; images from IGDB
or SteamGridDB can fill empty covers. Banner/logo/icon URLs remain available
as optional columns and in exports.

OpenCritic combines platforms; it does not replace the PC Metacritic score
or affect its minimum-score filter. IGDB ratings are separate as well.
Source-specific columns can be sorted through the normal table/sort selector.
ProtonDB uses the site's public summary endpoint, whose format may change.

Successful entries are cached for seven days, unmatched/failed entries for a
day. A newly available Steam mapping rechecks a previously missing ProtonDB
lookup. The first run across a large library can take a while; duplicate
lookups are reused within the run. Requests are sequential and paced; Stop
keeps results already saved. Authorization/rate-limit failures pause the
affected source and let the other sources continue. Three network/service
failures in succession also pause that source. Retry-After is respected;
correcting a credential allows a new attempt without waiting for the old
key's pause. Existing enrichment values survive failures and store refreshes.

Verification: offline tests cover matching, ambiguous editions, PC counts,
IGDB token renewal, credential correction, cancellation, persistent rate-limit
waits, source isolation, artwork attribution, export/import and settings.
ProtonDB was also checked live. The credential-based integrations require
your credentials for an end-to-end account check.


### Missing values and database status (v0.32)

Missing-value labels use a purple dash (—) in tables, cover cards, filters,
reports, details and logs. Stored values, source-state identifiers and export
data retain their original form so existing filters and saved views keep working.

A second status row under the store connections shows Metacritic, IGDB,
ProtonDB, SteamGridDB and OpenCritic. Green means a live access check succeeded;
blue means checking; amber means setup, credentials, access or request limits
need attention; red means the service could not be reached or its response was
unexpected. Disabled sources are gray. Hover a name or icon for details and
the last check time. Click the database strip to request a check.

Database checks run hourly while the app is idle, pause during account/import/
export work and wait for completion before shutdown. Checks never change game
records. OpenCritic uses one request from the selected RapidAPI plan per check
and is limited to once per hour, including manual clicks. Server Retry-After
waits are respected. Changing its API key allows a fresh access check. Store
checks continue at their existing five-minute interval.


### Heroic install handoff and store visibility (v0.33)

Select an uninstalled Epic or GOG game and choose **Install with Heroic…**.
The app sends the exact Epic app name or GOG product ID to Heroic’s supported
game link. Heroic prompts to install an uninstalled game; confirmation,
location and other choices remain in Heroic. If Heroic already considers it
installed, that link may launch it instead. The button is hidden for entries
our scan marks installed, other stores, inactive entries and explicit DLC/
movie records. Rescan installations after Heroic finishes installing.

A configured Heroic executable/script from Installations… is preferred, then
the native `heroic` command. Otherwise the registered `heroic://` desktop
handler is used, supporting registered Flatpak and AppImage installations.
Failed handoffs are reported in the log. No installation starts during scans
or refreshes. The app does not choose an install directory or alter settings.
Heroic’s protocol implementation is documented in its source:
https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/blob/main/src/backend/protocol.ts

Each store status indicator now has a checkbox. Checked stores are visible;
unchecking every store shows no games. These choices combine with the other
filters, including the existing Store facet, and apply to table/cover views
and visible-row exports. They are saved with browsing settings and presets.
**Clear filters** restores all store checkboxes. The checkbox changes only
visibility; account refresh enablement and connection checks remain controlled
by Sources… independently.


### Sign-in crash isolation (v0.34)

EA and Steam website sign-in now run in a separate Python/Qt WebEngine
process. A native browser crash therefore does not terminate the library.
Connect EA / Connect Steam dates opens a small connection controller plus
the website window. Complete sign-in in the website window and choose
**Use this session** there. The normal verification, atomic cookie save and
automatic EA token renewal behavior are preserved.

Software rendering is enabled by default for the browser process only. If
the website window still stops, the controller stays open with **Retry
sign-in**. Try **Use X11 compatibility (XWayland)** as well on a Wayland
session. This setting uses the xcb backend only when DISPLAY is available.
No browser sandbox or web-security setting is disabled by this update.
The precise cause of a machine-specific native crash still requires its
crash diagnostics; the library now contains that failure independently.

Cancel closes the child process and waits for its exit before removing its
private temporary files. Only the service name and authentication directory
are passed to the child, not the other stores' credentials or API keys.
Passwords remain entered only on the official website. Browser output is
not copied into the library log. Sign-in cookies are still published only
after verification; otherwise the previously saved session remains in place.

Tests include a real forced native child abort, successful result handoff,
dependency errors, cancellation, private-file permissions and preservation
of the existing sign-in after failure. No live EA account was used in tests.


### English EA sign-in (v0.34.1)

The isolated sign-in browser now requests English through its browser language,
HTTP Accept-Language preference and EA locale=en_US login/redirect parameters.
Existing ealocale and PLAY_LANG preference cookies are set to English in the
private browser session. Authentication cookies remain intact; saved cookies
are still replaced only after a verified sign-in. OAuth state, redirect URLs
and other sign-in parameters are preserved, and form submissions are not
redirected by the locale handler.


### Open in Steam (v0.35)

Selecting a Steam entry shows **Open in Steam** in the game details panel.
It opens `steam://nav/games/details/<app-id>` in the Steam client, selecting
the game’s library page. It does not invoke a launch or installation command,
and is available for installed and uninstalled Steam entries. The configured
Steam executable from Installations… is preferred, then the native Steam
command, then the registered desktop protocol handler (including Flatpak).
Invalid app IDs and failed handoffs produce a clear error. A successful
handoff means the request was sent; it cannot confirm Steam’s window state.

## Selected metadata and match review (0.36)

Select games with Ctrl/Shift in either view, then choose **Fetch selected details…** from the toolbar or right-click menu. Choose sources explicitly; only Store details is selected initially. Store details fetches missing Steam/GOG/Epic metadata. Extra sources require their usual credentials. No account library refresh or acquisition-history fetch is performed.

**Retry cached results now** bypasses per-game waiting periods, while service-wide pauses and request limits remain in effect. OpenCritic requests can consume your subscription quota. Already saved results survive Stop or failed requests.

Use **Review metadata match…** for the current game to inspect each source's saved result, checked date, URL and ID. Supply an exact alternate lookup title for Metacritic, IGDB, SteamGridDB or OpenCritic; leave blank to restore the store title. This does not rename the catalog entry. Save, then fetch selected details. Lookup changes invalidate the relevant cache; existing values remain until verified replacements arrive. PC, edition, release-year and known Steam-ID checks remain enforced. ProtonDB uses exact Steam IDs; SteamGridDB prefers them over title lookup.

The review shows previously fetched entries; it does not search or browse candidate matches. Ambiguous titles remain unresolved rather than being guessed. Selected-game fetches and corrections were tested offline with mocked responses; live API credentials were not available here.

## Favorites and personal tags (0.37)

Select a game and choose **Favorite / tags…** from the toolbar or right-click menu. Mark it as a favorite and enter comma-separated tags such as With kids, Try next or Finished. Clear the tags field or uncheck Favorite to remove them. Each annotation belongs to one store entry; copies in other stores are independent. Duplicate tags are combined without regard to capitalization. Up to 40 tags of 60 characters each are supported.

Use **Favorites only**, the **Personal tags** picker, or the search field to find annotated games. The tag picker matches any checked tag, combined with the other filters. Favorites and personal tags also have optional table columns. Filters are remembered and can be saved in presets. Clear filters resets them.

Annotations are stored separately from store data and survive library refreshes and metadata fetches. JSON exports preserve the annotations for import; CSV includes Favorite and Personal tags columns. No account connection is needed to edit them.

## Advanced filters (0.38)

Open **Advanced filters…** beside the main filters. The button shows how many advanced conditions are active. These filters use already saved metadata and never contact websites.

Review filters cover Metacritic PC users (out of 10), IGDB users and critics (out of 100), OpenCritic average (out of 100, combined platforms), and OpenCritic recommendation percentage. Each offers Any, Known, Missing or Minimum. Known includes a published zero; Minimum excludes missing scores. The main Metacritic critic minimum remains a separate filter.

Set a minimum PC local-player count or local co-op count using IGDB data. Local multiplayer can include competitive games; the co-op filter specifically uses cooperative counts. A game with no count is excluded when a minimum is active. Counts are not inferred from genres.

Select one or more ProtonDB tiers, including No rating. Any checked tier matches; checking none allows all ratings. Unknown or absent ratings count as No rating. Community ratings are not a guarantee of compatibility.

Every advanced condition combines with the main filters. Filters persist across restarts and in saved presets. Reset in the dialog clears advanced controls (Apply commits them); Cancel keeps the previous filters. The main Clear filters action clears everything.

## Copies across stores (0.39)

Open **Copies across stores…** to compare possible copies from your entire saved library, including entries hidden by current filters or absent from the latest refresh. Groups show each store's installation status, acquisition date, favorite, personal tags, current-library presence and store ID. Search groups by title, store or tag.

Grouping is a suggestion based on the same normalized title. Case, punctuation and trademark symbols are ignored; edition words, numbers and Unicode letters remain significant. Groups require at least two different stores. Conflicting known content types or release years more than one year apart prevent grouping. Missing dates do not prove identity. Games are never merged, annotations stay separate, and no metadata is copied between stores. Hover over a group title to see the matching rule.

Select a child store entry and choose **Show selected copy (clears filters)**, or double-click it, to return to that exact store ID in the main catalog. This clears browsing filters and retains the current view and sort. The normal install/launch buttons then apply to that selected entry; the comparison itself does not launch, install or contact any store. If no groups are shown, no saved titles meet the conservative matching rule.

## Database backups and restore (0.40)

Open **Backups…** to create a full database snapshot or restore one of the saved snapshots. You can also choose a compatible database file copied from another installation. Snapshots are stored beside library.sqlite3 in the backups folder. Backup files are private (0600), in a private folder (0700).

A daily baseline is saved before the first background library operation of each local calendar day, provided the database contains games. This includes the installation scan normally run on startup. Imports also request a daily baseline before saving. This is a snapshot of the database before that operation, not an end-of-day archive or a scheduled task. A backup error prevents that operation from writing changes.

Retention is separate: 7 daily snapshots, 5 manual snapshots and 3 recovery snapshots. Rotation removes only recognized backup filenames of the same category after a new snapshot has been published. Failed cleanup can leave extra older files. Use Create backup now whenever you want a fresh checkpoint.

Snapshots contain all database tables: games, metadata, favorites, personal tags, installation scan data, source statuses, acquisition reports and retry state. Settings, API keys, website login files, launcher authentication, downloaded artwork and installed game files are not part of the database backup.

Restore checks the complete selected database before writing and replaces its four data tables in one transaction. It creates a recovery snapshot of the current database before replacement. Cancel before commit rolls back the restore; completed recovery snapshots are retained. To undo a restore, open Backups again and restore its recovery copy. Settings and sign-ins remain unchanged. Rescan installations after restoring old data if you need current installation status.

Backups and restores run in the background and use the normal Stop control. The catalog reloads after a successful restore. SQLite snapshotting includes committed WAL data; no direct copy of a live database file is used. The restore size limit is 512 MiB.

## Request budgets and fetch progress (0.41)

Each extra metadata source has **HTTP requests per fetch (0 = unlimited)** in Sources. OpenCritic defaults to 50 calls per fetch; IGDB, ProtonDB and SteamGridDB default to no local cap. The Fetch selected details dialog shows the current caps before starting. Caps apply to both bulk and selected-game extra fetches, including Retry cached results.

Progress now names the source, current game/total, and API calls attempted against its cap. Final log summaries include the actual call count. Failed API calls, authentication requests and retries count; cached results do not. A game may require several calls: OpenCritic usually searches then requests details, while SteamGridDB can request four artwork categories after finding the game.

The cap is checked before every API call. On reaching it, that source stops for this fetch and other selected sources continue. Already completed games stay saved. An unfinished game is not marked unavailable or put into a negative cache solely because the budget ran out. A partially retrieved game's new metadata is not committed. A later fetch can skip completed cached games and continue; a cap too small to finish one game must be raised.

These are per-operation limits, not a daily/monthly balance or billing guarantee. They reset when you start another fetch. Existing service-wide rate-limit pauses still apply. Connection checks and other applications using the same API key are outside these fetch budgets and may consume subscription quota. No subscription is purchased or changed.

## OpenCritic quota-aware fetching (0.42)

Normal OpenCritic responses now capture allowlisted RapidAPI quota headers, including plan request quotas, additional billing objects and the free-plan hard limit when supplied. Remaining balances and relative reset seconds are converted to local-friendly dates. Headers from HTTP error responses are captured too; receiving quota headers alone does not mark API access as successful.

Open **OpenCritic quota…** for the latest observed balances, reset times, last check, access result and queued game count. The dialog refreshes its saved display every two seconds without sending API requests. The toolbar badge updates about every 30 seconds and has a quota tooltip. Account API keys and arbitrary response headers are never copied into quota reports.

Every OpenCritic API call, including connection checks, reserves an allowance before sending. Two calls are held in reserve. Search-plus-detail fetches normally require at least two usable calls before beginning a game. Known daily/monthly/hard-limit buckets are all enforced; unknown reset times are never guessed. Local requests sharing the same quota file are serialized through response observation to avoid overlapping local balance updates. Other applications or keys using the same subscription can still consume quota outside Magik's knowledge.

When quota prevents a game from finishing, it is queued without a negative metadata cache. The queue persists across restarts. With reported quota still available, reaching the per-fetch cap schedules another batch after at least one minute; once allowance is low, continuation waits for the reported reset. Thus the local cap limits each automatic batch, not total automatic use. After a reset, one request verifies the renewed allowance before further calls proceed. If fresh headers do not confirm renewal, fetching pauses. HTTP 429 honors Retry-After (at least 60 seconds; one hour when absent). No API calls are made just to poll the balance.

Automatic continuation is enabled by default and can be disabled on the OpenCritic Sources tab. It runs only while Magik is open and idle, with OpenCritic enabled and credentials present. Existing source-level pauses remain enforced. Stop cancels queued OpenCritic work as well as the active extra-data fetch; the quota dialog also offers **Cancel queued games**. Paused work resumes after reopening an idle app when eligible.

If the API supplies no usable quota headers, manual per-fetch caps remain the fallback and unverified work is not automatically repeated. If a bucket lacks a reset time, automatic renewal cannot be scheduled. Connection checks reuse quota observations less than an hour old and respect the same reservation gate.

Quota state is stored separately in the private account-data folder, bound to an API-key fingerprint. It is not rolled back by a library database restore. Balances are last-observed values adjusted for local attempts, not a guarantee against charges or a substitute for the provider billing dashboard. Your actual subscription's headers must be verified on your machine: this release was tested with mocked HTTP responses, including the real transport's header-capture path. Start a selected-game OpenCritic fetch to learn your plan's headers.

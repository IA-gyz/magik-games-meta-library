"""Explicit sign-in UI. Accounts are entered only into the service's own website."""

from ui_actions import action_button
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from PySide6.QtCore import QThread, Signal, QUrl, QDateTime, Qt, QTimer
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel
from web_sessions import WebsiteSession, allowed_domain, valid_cookie, SessionError
from session_verification import verify_candidate


def english_ea_url(value):
    """Set language only on official EA sign-in navigation; preserve OAuth fields."""
    parts = urlsplit(value)
    host = parts.hostname or ""
    if parts.scheme != "https" or not (host == "ea.com" or host.endswith(".ea.com")):
        return value
    query = parse_qsl(parts.query, keep_blank_values=True)
    if not (
        any(key == "locale" for key, _ in query)
        or parts.path.endswith("/login")
        or parts.path == "/connect/auth"
    ):
        return value
    if [v for k, v in query if k == "locale"] == ["en_US"]:
        return value
    query = [(key, val) for key, val in query if key != "locale"] + [
        ("locale", "en_US")
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


class CheckSession(QThread):
    checked = Signal(object, str)

    def __init__(self, service, options, candidate, parent=None):
        super().__init__(parent)
        self.service = service
        self.options = options
        self.candidate = candidate

    def run(self):
        try:
            result = verify_candidate(self.service, self.options, self.candidate)
            self.checked.emit(result, "")
        except Exception:
            self.checked.emit(
                None,
                "This sign-in could not be verified or saved. Your previous saved sign-in was kept. Finish signing in, including any verification code, then try Use this session again.",
            )


class ConnectSession(QDialog):
    def __init__(self, service, options, parent=None):
        # Import lazily: browsing and manual-token workflows work without Qt WebEngine.
        try:
            from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            raise SessionError(
                "Sign-in needs Qt WebEngine. On CachyOS/Arch install: sudo pacman -S --needed pyside6 qt6-webengine. Then restart the app."
            ) from None
        super().__init__(parent)
        self.setWindowTitle(
            "Connect " + ("EA" if service == "ea" else "Steam dates added")
        )
        self.resize(1100, 820)
        self.service = service
        self.options = options.copy()
        self.result_data = {}
        self.checker = None
        self.cookies = {}
        self.cleaned = False
        layout = QVBoxLayout(self)
        self.hint = QLabel(
            "Sign in on the official website below and complete any verification steps. Then choose Use this session. The app saves sign-in cookies on this computer so it can reconnect later; it does not collect your password."
        )
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.address = QLabel()
        self.address.setTextFormat(Qt.PlainText)
        self.address.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.address)
        self.profile = QWebEngineProfile(
            self
        )  # Off the record: only our scoped cookie JSON is persisted.
        self.profile.setHttpAcceptLanguage("en-US,en;q=0.9")
        self.view = QWebEngineView(self)

        class LoginPage(QWebEnginePage):
            def acceptNavigationRequest(page, url, navigation_type, is_main_frame):
                target = (
                    english_ea_url(url.toString())
                    if service == "ea"
                    and is_main_frame
                    and navigation_type
                    != QWebEnginePage.NavigationType.NavigationTypeFormSubmitted
                    else url.toString()
                )
                if target != url.toString():
                    QTimer.singleShot(0, lambda: page.setUrl(QUrl(target)))
                    return False
                return super().acceptNavigationRequest(
                    url, navigation_type, is_main_frame
                )

        self.page = LoginPage(self.profile, self.view)
        self.view.setPage(self.page)
        layout.addWidget(self.view, 1)
        self.store = self.profile.cookieStore()
        self.store.cookieAdded.connect(self.add_cookie)
        self.store.cookieRemoved.connect(self.remove_cookie)
        prior = WebsiteSession(service, options)
        for record in prior.cookies():
            record = dict(record)
            if service == "ea" and record["name"] in ("ealocale", "PLAY_LANG"):
                record["value"] = "en-us" if record["name"] == "ealocale" else "en-US"
            cookie = QNetworkCookie(record["name"].encode(), record["value"].encode())
            cookie.setDomain(record["domain"])
            cookie.setPath(record["path"])
            cookie.setSecure(record["secure"])
            cookie.setHttpOnly(record["http_only"])
            if record["expires"]:
                cookie.setExpirationDate(
                    QDateTime.fromSecsSinceEpoch(int(record["expires"]))
                )
            self.store.setCookie(
                cookie, QUrl("https://" + record["domain"].lstrip(".") + record["path"])
            )
            self.cookies[(record["name"], record["domain"], record["path"])] = record
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        back = action_button("Back", "settings")
        back.clicked.connect(self.view.back)
        buttons.addWidget(back)
        login = action_button("Login page", "sync")
        login.clicked.connect(self.load_login)
        buttons.addWidget(login)
        buttons.addStretch()
        self.use = action_button("Use this session", "sync")
        self.use.clicked.connect(self.verify)
        buttons.addWidget(self.use)
        cancel = action_button("Cancel", "settings")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.view.urlChanged.connect(
            lambda url: self.address.setText(
                url.scheme() + "://" + url.host() + url.path()
            )
        )
        self.page.renderProcessTerminated.connect(self.renderer_failed)
        self.load_login()

    def renderer_failed(self, status, code):
        self.hint.setText(
            "The sign-in page stopped unexpectedly. Choose Login page to retry, or Cancel and enable software rendering / X11 compatibility in the connection window."
        )

    def load_login(self):
        self.view.setUrl(
            QUrl(
                "https://www.ea.com/login?locale=en_US"
                if self.service == "ea"
                else "https://store.steampowered.com/login/?redir=account%2Flicenses%2F&l=english"
            )
        )

    def add_cookie(self, cookie):
        domain = cookie.domain()
        if not allowed_domain(self.service, domain):
            return
        record = {
            "name": bytes(cookie.name()).decode("utf-8", errors="replace"),
            "value": bytes(cookie.value()).decode("utf-8", errors="replace"),
            "domain": domain,
            "path": cookie.path() or "/",
            "secure": cookie.isSecure(),
            "http_only": cookie.isHttpOnly(),
            "expires": None
            if cookie.isSessionCookie()
            else cookie.expirationDate().toSecsSinceEpoch(),
        }
        if valid_cookie(self.service, record):
            self.cookies[(record["name"], domain, record["path"])] = record

    def remove_cookie(self, cookie):
        self.cookies.pop(
            (
                bytes(cookie.name()).decode("utf-8", errors="replace"),
                cookie.domain(),
                cookie.path() or "/",
            ),
            None,
        )

    def verify(self):
        if self.checker and self.checker.isRunning():
            return
        candidate = {
            "cookies": list(self.cookies.values()),
            "user_agent": self.profile.httpUserAgent(),
        }
        self.pending_result = None
        self.pending_error = (
            "The sign-in check could not finish. Your previous saved sign-in was kept."
        )
        self.use.setEnabled(False)
        self.hint.setText(
            "Checking this sign-in… Your previous saved sign-in will be kept unless this check succeeds."
        )
        self.checker = CheckSession(self.service, self.options, candidate, self)
        self.checker.checked.connect(self.checked)
        self.checker.finished.connect(self.check_finished)
        self.checker.start()

    def checked(self, result, error):
        self.pending_result = result
        self.pending_error = error

    def check_finished(self):
        self.use.setEnabled(True)
        if getattr(self, "pending_result", None) is not None:
            self.result_data = self.pending_result
            self.accept()
        else:
            self.hint.setText(
                getattr(
                    self,
                    "pending_error",
                    "The session could not be verified. Try signing in again.",
                )
            )

    def done(self, result):
        if self.checker and self.checker.isRunning():
            return
        if self.cleaned:
            return
        self.cleaned = True
        self.view.stop()
        # Pages must be destroyed before their private profile.
        self.page.setParent(None)
        self.profile.setParent(None)
        self.page.destroyed.connect(self.profile.deleteLater)
        self.page.deleteLater()
        super().done(result)

    def reject(self):
        if self.checker and self.checker.isRunning():
            self.hint.setText(
                "Please wait for the login check to finish (up to 30 seconds)."
            )
            return
        self.view.stop()
        super().reject()

    def closeEvent(self, event):
        if self.checker and self.checker.isRunning():
            event.ignore()
            return
        super().closeEvent(event)

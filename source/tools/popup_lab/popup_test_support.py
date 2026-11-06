"""Explicit simulated services and first-run invitation for the TEST ZIP only.

Not in the production package manifest. No provider, publication, output, audio,
or credential-schema changes. The regular release UI/worker logic is exercised.
"""
import io
import json
import threading
import urllib.error
from urllib.parse import parse_qs, urlsplit

from qt.core import QObject, QTimer, QPushButton, QLabel, QComboBox, QFormLayout, QDesktopServices, QUrl
from calibre.constants import config_dir
from calibre_plugins.manganana.app.settings.config import prefs
from calibre_plugins.manganana.presentation.non_modal_window import PluginDialog, PluginMessageBox
from calibre_plugins.manganana.app.updates import release_updates; from calibre_plugins.manganana.app.updates import release_updates_ui; from calibre_plugins.manganana.app.settings import google_books_credentials
from calibre_plugins.manganana.tools.popup_lab.popup_test_state import ensure_profile, lock_profile

_LOCK = None
_INSTALLED = False
EVENTS = []
_EVENT_LOCK = threading.Lock()
UPDATE_SCENARIOS = ('official', 'none', 'newer', 'older', 'offline', 'rate-limit')
GOOGLE_SCENARIOS = ('success', 'invalid', 'offline', 'quota', 'unexpected')
_OFFICIAL_FETCH = release_updates.fetch
_OFFICIAL_CHECK = release_updates_ui.check_release
_OFFICIAL_DOWNLOAD = release_updates_ui.download_release
_REFRESH = release_updates_ui.ReleaseUpdates.refresh_indication
_OPEN_NOTES = release_updates_ui.ReleaseUpdates.open_release_page
_DOWNLOADED = release_updates_ui.ReleaseUpdates.downloaded


def simulated_release():
    """Use the existing version/asset selector, without inventing a public release."""
    raw = release_response(release_updates.API_URL, 10000, scenario='newer')
    selected = release_updates.select_release(json.loads(raw), release_updates_ui.SEMANTIC_VERSION)
    selected['_popup_simulated'] = True
    return selected


def record(kind, scenario):
    with _EVENT_LOCK:
        EVENTS.append(dict(kind=kind, scenario=scenario, thread=threading.get_ident()))
        del EVENTS[:-200]


def release_response(url, limit, cancelled=lambda: False, scenario=None):
    if cancelled():
        raise InterruptedError('Test check cancelled')
    scenario = scenario or prefs.get('popup_test_update_scenario', 'official')
    if scenario == 'official':
        return _OFFICIAL_FETCH(url, limit, cancelled)
    if url != release_updates.API_URL:
        raise RuntimeError('TEST BUILD: release downloads and installation are disabled.')
    record('github', scenario)
    if scenario == 'offline':
        raise urllib.error.URLError('TEST RESPONSE: offline')
    if scenario == 'rate-limit':
        raise urllib.error.HTTPError(url, 429, 'TEST RESPONSE: rate limit', {}, io.BytesIO(b''))
    if scenario not in ('newer', 'older'):
        return b'[]'
    version = '0.14.1' if scenario == 'newer' else '0.13.9'
    return json.dumps([dict(tag_name='v' + version, draft=False, prerelease=False, assets=[dict(
        name='MangaAnka-v' + version + '.zip', size=1,
        browser_download_url='https://github.com/' + release_updates.REPOSITORY +
        '/releases/download/v' + version + '/MangaAnka-v' + version + '.zip')])]).encode()


class GoogleResponse(io.BytesIO):
    status = 200


def google_response(request, timeout=12):
    """Never transmit a credential, including accidentally entered real keys."""
    scenario = prefs.get('popup_test_google_scenario', 'invalid')
    record('google', scenario)
    url = request.full_url
    key = parse_qs(urlsplit(url).query).get('key', [''])[0]
    if scenario == 'offline':
        raise urllib.error.URLError('TEST RESPONSE: offline')
    if scenario == 'quota':
        raise urllib.error.HTTPError('https://www.googleapis.com/books/v1/volumes', 429,
            'TEST RESPONSE', {}, io.BytesIO(b'{"error":{"status":"RESOURCE_EXHAUSTED"}}'))
    if scenario == 'success' and key == 'popup-test-valid':
        return GoogleResponse(b'{"kind":"books#volumes","totalItems":0,"items":[]}')
    if scenario == 'unexpected':
        return GoogleResponse(b'{"test":"unexpected response"}')
    raise urllib.error.HTTPError('https://www.googleapis.com/books/v1/volumes', 400,
        'TEST RESPONSE', {}, io.BytesIO(b'{"error":{"reason":"API_KEY_INVALID"}}'))


class TestUpdateBox(PluginMessageBox):
    def exec(self):
        owner = self.parentWidget()
        release = getattr(getattr(owner, 'release_updates', None), 'release', None) or {}
        simulated = release.get('_popup_simulated', False)
        if simulated or prefs.get('popup_test_update_scenario', 'official') != 'official':
            self.setWindowTitle('TEST RESPONSE — ' + self.windowTitle())
        if simulated and 'update available' in self.windowTitle():
            self.setText('Simulated update: ' + self.text())
            self.setInformativeText('Simulated release response. This does not assert that a public '
                'release exists. Downloading and installing this simulated release are disabled. '
                'Release notes open the official releases list.')
        elif 'update available' in self.windowTitle():
            self.setInformativeText('Official release information. Actual update downloading and '
                'installation remain disabled in this popup-testing build.')
        for button in self.buttons():
            if button.text() == 'Install':
                button.setEnabled(False)
        return super().exec()


def check_release(installed, cancelled=lambda: False):
    result = _OFFICIAL_CHECK(installed, cancelled)
    if result and prefs.get('popup_test_update_scenario', 'official') != 'official':
        result['_popup_simulated'] = True
    return result


def download_release(release, cancelled=lambda: False):
    raise RuntimeError('Popup test build: actual release downloads and installation are disabled.')


def refresh_indication(controller, message=None):
    _REFRESH(controller, message)
    if controller.active and (controller.release or {}).get('_popup_simulated'):
        controller.d.update_status.setText('TEST RESPONSE · ' + controller.status)
        controller.d.settings_button.setToolTip('Simulated update available — popup test only')


def open_release_page(controller):
    if controller.active and (controller.release or {}).get('_popup_simulated'):
        QDesktopServices.openUrl(QUrl('https://github.com/' + release_updates.REPOSITORY + '/releases'))
    else:
        _OPEN_NOTES(controller)


def downloaded(controller, raw):
    controller.failed('Popup test build: actual release downloads and installation are disabled.')


def install_transports():
    global _INSTALLED, _LOCK
    if _INSTALLED:
        return
    directory = ensure_profile(config_dir, existing=True)
    _LOCK = lock_profile(directory)
    release_updates.fetch = release_response
    release_updates_ui.check_release = check_release
    release_updates_ui.download_release = download_release
    release_updates_ui.QMessageBox = TestUpdateBox
    release_updates_ui.ReleaseUpdates.refresh_indication = refresh_indication
    release_updates_ui.ReleaseUpdates.open_release_page = open_release_page
    release_updates_ui.ReleaseUpdates.downloaded = downloaded
    google_books_credentials.open_google_books = google_response
    # Reference lookup imports this boundary by value; keep the dummy key local.
    from calibre_plugins.manganana.metadata.references import google_books_reference
    google_books_reference.open_google_books = google_response
    _INSTALLED = True


class PopupLaboratory(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.d = dialog
        self.active = True
        self.panel = None
        self._simulate_pending = False
        dialog.finished.connect(self.detach)
        button = QPushButton('Popup laboratory (test build)', dialog.fidelity.settings_window)
        button.setObjectName('popupLaboratoryButton')
        button.clicked.connect(self.open_panel)
        layout = dialog.fidelity.settings_window.layout()
        layout.insertWidget(layout.count() - 1, button)
        simulate = QPushButton('Simulate Update Available', dialog.fidelity.settings_window)
        simulate.setObjectName('simulateUpdateAvailable')
        simulate.clicked.connect(self.simulate_update)
        layout.insertWidget(layout.count() - 1, simulate)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.invite)
        self.timer.start(0)

    def invite(self):
        if not self.active or self.d._closing or prefs.get('popup_test_google_invited', False):
            return
        if google_books_credentials.has_api_key():
            return
        if self.d.nonmodal_session.defer_notice(self.invite, 'Optional Google Books setup'):
            return
        prefs['popup_test_google_invited'] = True
        box = PluginMessageBox(self.d)
        box.setWindowTitle('MangaAnkā · Google Books Integration')
        box.setText('Google Books Integration')
        box.setInformativeText('MangaAnkā can use Google Books to find additional manga metadata '
            'and volume covers. This feature is optional.\n\n'
            'You can set it up anytime under Settings → Google Books.')
        opening = box.addButton('Set Up', box.ButtonRole.AcceptRole)
        later = box.addButton('Not Now', box.ButtonRole.RejectRole)
        box.setDefaultButton(later)
        box.exec()
        chosen = box.clickedButton()
        box.deleteLater()
        if chosen is opening and self.active and not self.d._closing:
            self.d.open_google_books_key()

    def simulate_update(self):
        if not self.active or self.d._closing:
            return
        updates = self.d.release_updates
        if updates.worker is not None:
            if not self._simulate_pending:
                self._simulate_pending = True
                updates.worker.finished.connect(self._simulate_settled)
            return
        if self.panel is not None:
            self.panel.hide()
        self.d.fidelity.settings_window.hide()
        updates.manual = True  # Explicit test action, like a manual update check.
        updates.checked(simulated_release())

    def _simulate_settled(self):
        self._simulate_pending = False
        if self.active and not self.d._closing:
            QTimer.singleShot(0, self.simulate_update)

    def open_panel(self):
        if not self.active or self.d._closing:
            return
        if self.panel is None:
            self.panel = PluginDialog(self.d)
            self.panel.setWindowTitle('MangaAnkā · Popup laboratory — TEST ONLY')
            form = QFormLayout(self.panel)
            label = QLabel('Simulated services. No real credentials or update installations.\n'
                'Close Calibre and use the reset utility to repeat onboarding.')
            label.setWordWrap(True); form.addRow(label)
            for title, key, values, default in (
                ('GitHub response', 'popup_test_update_scenario', UPDATE_SCENARIOS, 'official'),
                ('Google Books response', 'popup_test_google_scenario', GOOGLE_SCENARIOS, 'invalid')):
                combo = QComboBox()
                combo.setObjectName(key)
                combo.addItems(values)
                combo.setCurrentText(prefs.get(key, default))
                combo.currentTextChanged.connect(lambda value, name=key: prefs.__setitem__(name, value))
                form.addRow(title, combo)
            vl = QPushButton('Exercise Virtual Library prompt')
            vl.clicked.connect(self.virtual_library)
            api = QPushButton('Open optional Google Books setup')
            api.clicked.connect(self.d.open_google_books_key)
            update = QPushButton('Check simulated updates')
            update.clicked.connect(lambda: self.d.release_updates.check(manual=True))
            form.addRow(vl); form.addRow(api); form.addRow(update)
            done = QPushButton('Done'); done.clicked.connect(self.panel.hide); form.addRow(done)
        self.d.fidelity.settings_window.hide()
        self.panel.show(); self.panel.raise_(); self.panel.activateWindow()

    def virtual_library(self):
        if self.active and not self.d._closing:
            self.d.maybe_offer_virtual_library()

    def detach(self, *_):
        self.active = False
        self.timer.stop()


def attach(dialog):
    install_transports()
    return PopupLaboratory(dialog)

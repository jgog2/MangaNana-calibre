"""Opt-in local catalog choice in the existing Finalization/Review stage."""
from copy import deepcopy
import json
import os
from qt.core import QWidget, QVBoxLayout, QComboBox, QLabel, QThread, pyqtSignal, Qt
from calibre_plugins.manganana.publication.catalog_reader import load_catalog, decide, selected_groups


class CatalogLoadWorker(QThread):
    ready = pyqtSignal(object)

    def __init__(self, path, context, groups, parent=None):
        super().__init__(parent)
        self.path = path; self.context = deepcopy(context); self.groups = deepcopy(groups)

    def run(self):
        try:
            data = load_catalog(self.path)
            # This evaluates a candidate offer. Only choosing it in Review
            # establishes the session's requested layout and consent.
            context = dict(self.context, layout_id=data['record']['layout']['layout_id'])
            rows = tuple(row for group in self.groups for row in group.get('chapters') or ())
            result = decide(data, context, rows, self.groups)
        except Exception as exc:
            result = {'decision': 'ineligible', 'reason': 'Local catalog unavailable: '+str(exc)}
        self.ready.emit(result)


class CatalogReview(QWidget):
    """No persistent preferences or implicit mapping selection."""
    def __init__(self, changed, parent=None, enabled=None, path=None):
        super().__init__(parent)
        self.enabled = os.environ.get('MANGAANKA_CATALOG_ENABLED') == '1' if enabled is None else bool(enabled)
        self.path = os.environ.get('MANGAANKA_CATALOG_PATH', '') if path is None else str(path)
        self.changed = changed; self._key = None; self._decision = {}; self._selected = False
        self._workers = []; self._generation = 0
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.choice = QComboBox(self); self.choice.setAccessibleName('Publication mapping source')
        self.choice.addItem('Current live mapping', 'live')
        self.detail = QLabel(self); self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.choice); layout.addWidget(self.detail)
        self.choice.currentIndexChanged.connect(self._choose)
        self.setVisible(self.enabled and bool(self.path))

    @property
    def selection_token(self):
        return self._decision.get('selection_token', '') if self._selected else ''

    def prepare(self, context, live_groups):
        if not self.enabled or not self.path:
            return None
        self.setVisible(True)
        key = json.dumps({'context': context, 'groups': live_groups}, sort_keys=True, default=str)
        if key != self._key:
            self._key = key; self._generation += 1; generation = self._generation
            self._selected = False; self._decision = {}
            self.choice.blockSignals(True); self.choice.clear(); self.choice.addItem('Current live mapping', 'live'); self.choice.blockSignals(False)
            self.detail.setText('Checking optional local catalog; current live mapping remains selected.')
            worker = CatalogLoadWorker(self.path, context, live_groups, self)
            self._workers.append(worker)
            worker.ready.connect(lambda value, token=generation: self._loaded(value, token))
            worker.finished.connect(lambda w=worker: self._finished(w))
            worker.start()
        if self._selected:
            return selected_groups(self._decision, live_groups, explicit_selection=True)
        return None  # Leave the caller's native/grouped path exactly unchanged.

    def clear_context(self):
        self._generation += 1; self._key = None; self._selected = False; self._decision = {}
        self.choice.blockSignals(True); self.choice.clear(); self.choice.addItem('Current live mapping', 'live'); self.choice.blockSignals(False)
        self.hide()

    def _finished(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def _loaded(self, decision, generation):
        if generation != self._generation:
            return
        self._decision = decision
        if decision['decision'] == 'ineligible':
            missing = decision.get('missing_required_relationships') or []
            detail = '; '.join('Chapter '+str(r.get('chapter') or r['acquisition_id'])+' has no supported catalog relationship' for r in missing)
            self.detail.setText(decision['reason']+('. '+detail if detail else ''))
            return
        label = decision['layout']['label']; qualification = decision['qualification']
        self.choice.blockSignals(True)
        self.choice.addItem('Catalog mapping — '+label+' ('+qualification+')', 'catalog')
        self.choice.blockSignals(False)
        differences = '; '.join(
            ('Provider chapter '+r['provider_chapter']+' → canonical Chapter '+r['chapter_id']
             if 'provider_chapter' in r else 'Chapter '+r['chapter_id'])+
            ': volume '+str(r['live'])+' → '+str(r['catalog'])
            for r in decision['differences']) or 'No membership differences in selected output.'
        self.detail.setText(label+' | '+qualification+' | revision '+decision['catalog_revision']+
            '\n'+differences+'\n'+'; '.join(decision['uncertainties'])+
            '\nUnresolved identities outside requested output: '+str(len(decision['unresolved_identities']))+
            '\nChoose the catalog mapping explicitly to use this selected subset; consent lasts only for this session/context.')

    def _choose(self, _index):
        selected = self.choice.currentData() == 'catalog'
        if selected == self._selected:
            return
        self._selected = selected
        self.changed()

    def stop(self):
        # Only a bounded local file is read; no network/cancellation dependency.
        self._generation += 1
        for worker in tuple(self._workers):
            worker.wait()

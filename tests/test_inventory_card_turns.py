"""Card work yields while the full exact item model remains selectable."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from qt.core import QApplication, QListWidget, QListWidgetItem, QLabel

tree=ast.parse((Path(__file__).resolve().parents[1]/'presentation/choose_manga_ui.py').read_text(encoding='utf8'))
method=next(n for c in tree.body if isinstance(c,ast.ClassDef) for n in c.body
            if isinstance(n,ast.FunctionDef) and n.name=='_materialize_chapter_cards')
ns={};exec(compile(ast.Module(body=[method],type_ignores=[]),'card turns','exec'),ns)
materialize=ns[method.name]

class CardTurnTests(unittest.TestCase):
    def test_yielding_materialization_keeps_identity_and_tracks_changed_viewport(self):
        app=QApplication.instance() or QApplication([])
        view=QListWidget();timers=[];created=[];target=[range(11)]
        for i in range(20):
            item=QListWidgetItem();item.setData(256,dict(kind='chapter',id='exact:'+str(i)));view.addItem(item)
        def create(item):created.append(item.data(256)['id']);view.setItemWidget(item,QLabel('Cover'))
        owner=SimpleNamespace(_closing=False,workflow_mode='chapter',volume_list=view,
            workflow_state=SimpleNamespace(chapter_presentation_frozen=True),
            _visible_row_range=lambda *_:target[0],
            _live_inventory_items=lambda:[view.item(i)for i in range(view.count()) if view.itemWidget(view.item(i)) is not None],
            _chapter_card_timer=SimpleNamespace(start=lambda delay:timers.append(delay)),
            _create_chapter_card=create,_arrange_inventory=lambda **_:None,_load_visible_volume_thumbs=lambda:None)
        materialize(owner)
        self.assertEqual(3,len(created));self.assertEqual([0],timers)
        self.assertEqual(20,view.count())
        target[0]=range(10,20)
        for _ in range(4):materialize(owner)
        self.assertEqual(['exact:'+str(i)for i in range(10,20)],
            [view.item(i).data(256)['id']for i in range(20)if view.itemWidget(view.item(i))is not None])
        before=list(created);owner._closing=True;materialize(owner);self.assertEqual(before,created)
        view.deleteLater();app.processEvents()

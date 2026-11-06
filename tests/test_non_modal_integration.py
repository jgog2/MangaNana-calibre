from tools.source_bootstrap import source_file
"""Pinned-library identities, scoped dialogs and nested duplicate decisions."""
import copy,hashlib,importlib.util,json,sys,types,unittest,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def load(name):
    spec=importlib.util.spec_from_file_location(name,source_file(name, ROOT))
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module

destination=load('calibre_destination')
outputs=load('output_import')

class Database:
    library_path='C:/disposable/library-a'
    library_id='library-a-uuid'
    def __init__(self):
        self.new_api=self;self.calls=[]
    def field_for(self,*args):self.calls.append(args);return 'metadata'

class DestinationTests(unittest.TestCase):
    def setUp(self):
        self.gui=type('Gui',(),{})();self.gui.current_db=Database();self.gui.shutting_down=False
        self.session=destination.PinnedDestination(self.gui)

    def test_reopened_library_resolves_fresh_api(self):
        method=self.session.database.field_for;old=self.gui.current_db
        self.gui.current_db=Database();method('title',1)
        self.assertFalse(old.calls);self.assertEqual(self.gui.current_db.calls,[('title',1)])

    def test_same_path_different_uuid_is_rejected(self):
        self.gui.current_db=Database();self.gui.current_db.library_id='replacement'
        with self.assertRaises(destination.DestinationUnavailable):self.session.database.field_for('title',1)

    def test_same_uuid_different_path_is_rejected(self):
        self.gui.current_db=Database();self.gui.current_db.library_path='C:/disposable/library-b'
        self.assertFalse(self.session.available())

    def test_transition_and_shutdown_never_expose_old_handle(self):
        self.session.switching=True
        self.assertFalse(self.session.available());self.session.switching=False
        self.gui.shutting_down=True;self.assertFalse(self.session.available())
        self.gui.shutting_down=False;self.session.closed=True;self.assertFalse(self.session.available())

    def test_transition_never_reads_a_detached_database(self):
        self.session.switching=True;self.gui.current_db=object()
        self.assertFalse(self.session.available())

    def test_rejected_import_is_explicit_conflict(self):
        self.assertEqual(destination.RejectedImporter('wrong library').import_one(None,None)['status'],'conflicted')

class MutableLibrary:
    def __init__(self,key):
        self.records={1:dict(title='Before',authors=('Author',),series='Series',series_index=1,identifiers={'mangaanka_output':key})}
    def all_book_ids(self):return set(self.records)
    def field_for(self,name,bid):return copy.deepcopy(self.records[bid].get(name))
    def has_format(self,*_):return True
    def format_metadata(self,*_,**__):return dict(size=25,mtime=1)

class DuplicateDecisionTests(unittest.TestCase):
    def test_changed_or_deleted_book_is_not_replaced(self):
        from calibre.ebooks.metadata.book.base import Metadata
        payload={'source_id':'test','kind':'chapter','chapter_id':'exact'}
        key='v2:'+hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        item=dict(output_identity=key,output_acquisition=payload,format='cbz')
        for mutation in ('edit','delete','identity','tags','language'):
            db=MutableLibrary(key);importer=outputs.OutputImporter(db)
            def decide(*_):
                if mutation=='delete':db.records.clear()
                elif mutation=='edit':db.records[1]['title']='User edited in Calibre'
                elif mutation=='tags':db.records[1]['tags']=('User tag',)
                elif mutation=='language':db.records[1]['languages']=('jpn',)
                else:db.records[1]['identifiers']={}
                return 'replace'
            result=importer.import_one(item,Metadata('Before',['Author']),'ask',decide)
            self.assertEqual(result['status'],'conflicted')

    def test_incremental_reconciliation_conserves_partial_cancel_and_unexpected_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'output.cbz';path.write_bytes(b'controlled accounting fixture')
            requests=[dict(output_identity=k,title=k) for k in ('first','second','third')]
            files=[dict(output_identity=k,path=str(path),format='cbz') for k in ('first','second','third','unexpected')]
            class Importer:
                def import_one(self,*_):return dict(status='imported',verified={'book_id':1})
            run=outputs.OutputReconciliation(requests,files,Importer(),lambda _:None,'skip')
            run.step();run.cancel_requested=True
            while not run.done:run.step()
            ledger=run.result()
            self.assertEqual([r['output_identity'] for r in ledger['outputs']],['first','second','third'])
            self.assertEqual(ledger['counts']['imported'],1);self.assertEqual(ledger['counts']['cancelled'],2)
            self.assertEqual(ledger['unexpected'][0]['output_identity'],'unexpected')

class ScopedDialogTests(unittest.TestCase):
    def test_plugin_children_are_window_modal(self):
        from qt.core import QApplication,QWidget,Qt
        app=QApplication.instance() or QApplication([])
        scoped=load('non_modal_window')
        root=QWidget();root.setProperty('mangaankaWindow',True)
        child=scoped.PluginDialog(root);message=scoped.PluginMessageBox(root)
        self.assertEqual(child.windowModality(),Qt.WindowModality.WindowModal)
        self.assertEqual(message.windowModality(),Qt.WindowModality.WindowModal)
        normal=scoped.PluginDialog()
        self.assertEqual(normal.windowModality(),Qt.WindowModality.NonModal)
        root.deleteLater();normal.deleteLater();app.processEvents()

if __name__=='__main__':unittest.main()

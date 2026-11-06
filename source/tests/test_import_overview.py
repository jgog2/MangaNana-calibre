"""Import presentation retains exact records while filenames and details separate."""
import copy,unittest
from pathlib import Path
from types import SimpleNamespace as S
from qt.core import QApplication,QTableWidget,Qt
from calibre_plugins.manganana.presentation.import_overview import ImportOverview
from calibre_plugins.manganana.presentation.mangaanka_widgets import MangaAnkaCheckBox


class ImportOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance()or QApplication([])

    def books(self):
        return [dict(id=str(i),title='Embedded title '+str(i),path=str(Path('folder'+str(i))/'same-name.cbz'),
                     format='cbz',pages=3+i,bytes=1024*(i+1),author='An author',series='A series')for i in range(2)]

    def test_same_names_remain_distinct_and_all_records_have_main_details(self):
        overview=ImportOverview();books=self.books();original=copy.deepcopy(books)
        overview.set_books(books,{'0'})
        self.assertEqual(2,overview.table.rowCount())
        self.assertEqual(['Yes','No'],[overview.table.item(i,4).text()for i in range(2)])
        self.assertEqual(['0','1'],[overview.table.item(i,0).data(Qt.ItemDataRole.UserRole)for i in range(2)])
        self.assertEqual([b['path']for b in books],[overview.table.item(i,5).text()for i in range(2)])
        self.assertIn('An author',overview.table.item(0,0).toolTip())
        self.assertEqual('1.0 KiB',overview.table.item(0,3).text())
        self.assertEqual(original,books)
        overview.deleteLater();self.app.processEvents()

    def test_update_preserves_focused_record_and_reuses_unchanged_contents(self):
        overview=ImportOverview();books=self.books();overview.set_books(books,{'0'})
        overview.table.setCurrentCell(1,0);first=overview.table.item(0,0)
        overview.set_books(books,{'0'});self.assertIs(first,overview.table.item(0,0))
        overview.set_books(books,{'1'})
        self.assertIs(first,overview.table.item(0,0))
        self.assertEqual('1',overview.table.currentItem().data(Qt.ItemDataRole.UserRole))
        self.assertEqual(['No','Yes'],[overview.table.item(i,4).text()for i in range(2)])
        overview.set_books([],set());self.assertEqual(0,overview.table.rowCount())
        overview.deleteLater();self.app.processEvents()

    def test_sidebar_filename_does_not_replace_metadata_or_checkbox_identity(self):
        from calibre_plugins.manganana.books.imports.import_workflow import ImportWorkflowMixin
        books=self.books();changes=[]
        d=S(import_table=QTableWidget(0,4),_import_books=books,_selected_import_ids={'0'},
            _toggle_import=lambda identity,checked:changes.append((identity,checked)))
        original=copy.deepcopy(books);ImportWorkflowMixin._refresh_import_table(d)
        self.assertEqual(['same-name.cbz']*2,[d.import_table.item(i,1).text()for i in range(2)])
        self.assertNotEqual(d.import_table.item(0,1).toolTip(),d.import_table.item(1,1).toolTip())
        for index in range(2):d.import_table.cellWidget(index,0).findChild(MangaAnkaCheckBox).click()
        self.assertEqual([('0',False),('1',True)],changes);self.assertEqual(original,books)
        d.import_table.deleteLater();self.app.processEvents()


if __name__=='__main__':unittest.main()

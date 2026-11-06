"""Unknown page counts, whole-batch progress, and actual Qt text geometry."""
from pathlib import Path
from types import SimpleNamespace as S
import tempfile,time,unittest
from qt.core import QApplication,QTableWidget,QTableWidgetItem,QHeaderView,QHBoxLayout,QPushButton,QSize
from calibre_plugins.manganana.books.output.batch_progress import BatchProgress,import_percent
from calibre_plugins.manganana.books.output.final_output_view import SourcePillCell
from calibre_plugins.manganana.presentation.mangaanka_widgets import ElidedSummary
from tests.test_empress_pipeline import production_namespace,Source


class BatchProgressTests(unittest.TestCase):
    def test_unknown_or_revised_counts_do_not_reset_at_chapter_or_phase_boundaries(self):
        batch=BatchProgress([3,2]);values=[]
        for index,count in enumerate((3,2)):
            for chapter in range(count):
                for page in range(1,4):values.append(batch.update(index,'download',page,3,chapter))
            values.append(batch.update(index,'render',0,6))
            values.extend(batch.update(index,'render',n,6)for n in range(1,7))
            values.extend((batch.update(index,'write'),batch.update(index,'settled')))
        self.assertEqual(sorted(values),values);self.assertEqual(95,values[-1])
        self.assertTrue(all(value<100 for value in values))
        self.assertLess(batch.update(0,'download',1,999,0),100)
        self.assertEqual(95,batch.value)

    def test_local_books_share_the_batch_scale_and_import_reservation(self):
        batch=BatchProgress([0,0]);first=batch.update(0,'settled')
        self.assertLess(first,95)
        self.assertGreaterEqual(batch.update(1,'render',0,10),first)
        self.assertEqual(95,batch.update(1,'settled'))
        self.assertEqual([95,97,99],[import_percent(n,2)for n in range(3)])
        self.assertEqual(99,import_percent(100,2))

    def test_failed_output_advances_accounting_without_rewinding_remaining_work(self):
        batch=BatchProgress([2,1]);before=batch.update(0,'download',1,2,1)
        failed=batch.update(0,'settled')
        self.assertGreater(failed,before)
        self.assertGreaterEqual(batch.update(1,'download',1,100,0),failed)
        with self.assertRaises(ValueError):batch.update(0,'invented')

    def test_real_download_group_unknown_pages_never_reports_complete_or_rewinds(self):
        ns=production_namespace();source=Source()
        worker=ns['DownloadWorker'](source,'url','Title','Author','Series','en',None,None,False,False,())
        worker._current_output_metadata=dict(title='Title',series='Series',series_index=1,cover_number_kind='standalone')
        trace=[];worker.stats.connect(lambda d:trace.append(d['percent']))
        worker.progress.connect(lambda p,_:trace.append(p))
        state=dict(bytes=0,pages_done=0,pages_total=0,volume_done=0,started=time.time())
        with tempfile.TemporaryDirectory()as directory:
            worker._download_group([dict(id='a',chapter='1',pages=0),dict(id='b',chapter='2',pages=0)],
                Path(directory)/'sample.cbz','Title',None,'',state,1,1,0)
        self.assertEqual(sorted(trace),trace);self.assertLess(max(trace),100)
        self.assertEqual(6,state['pages_done'])


class TextGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance()or QApplication([])

    def test_status_elides_with_full_tooltip_and_recovers_on_resize(self):
        label=ElidedSummary();text='Batch 42% · Output 1/3 · Chapter 12/30 · Page 47/122 · Downloading'
        label.setText(text);label.resize(170,40);label.show();self.app.processEvents()
        self.assertEqual(text,label.full_text);self.assertEqual(text,label.toolTip())
        self.assertTrue(label.text().endswith('…'))
        self.assertLessEqual(label.fontMetrics().horizontalAdvance(label.text()),label.contentsRect().width())
        label.resize(1500,40);self.app.processEvents();self.assertEqual(text,label.text())
        label.setStyleSheet('font-size:24px;');self.app.processEvents()
        self.assertGreaterEqual(label.minimumSizeHint().height(),label.fontMetrics().height())
        label.close();label.deleteLater();self.app.processEvents()

    def test_source_pill_column_tracks_real_layout_and_font_changes(self):
        table=QTableWidget(1,1);table.resize(500,170)
        table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        table.setItem(0,0,QTableWidgetItem('WeebCentral'))
        cell=SourcePillCell();layout=QHBoxLayout(cell);layout.setContentsMargins(4,2,4,2)
        pill=QPushButton('◉ WeebCentral');layout.addWidget(pill)
        table.setCellWidget(0,0,cell);cell.bind(table,0,0);table.show()
        for pixels in (12,24,16):
            pill.setStyleSheet(f'font-size:{pixels}px;padding:4px 12px;')
            self.app.processEvents();self.app.processEvents()
            self.assertGreaterEqual(table.columnWidth(0),layout.minimumSize().width())
            self.assertGreaterEqual(pill.width(),pill.minimumSizeHint().width())
        table.setRowCount(0);self.app.processEvents();table.close();table.deleteLater();self.app.processEvents()

    def test_minimum_policy_cannot_shrink_a_pill_below_its_minimum_hint(self):
        from qt.core import QSize, QSizePolicy
        class Pill(QPushButton):
            def sizeHint(self):return QSize(95,22)
            def minimumSizeHint(self):return QSize(99,22)
        table=QTableWidget(1,1);table.resize(500,170)
        table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        table.setItem(0,0,QTableWidgetItem('Provider'))
        cell=SourcePillCell();layout=QHBoxLayout(cell);layout.setContentsMargins(4,2,4,2)
        layout.addStretch();pill=Pill('Provider');pill.setSizePolicy(QSizePolicy.Policy.Minimum,QSizePolicy.Policy.Fixed)
        layout.addWidget(pill);layout.addStretch()
        table.setCellWidget(0,0,cell);cell.bind(table,0,0);table.show()
        self.app.processEvents();self.app.processEvents()
        self.assertGreaterEqual(pill.width(),99)
        table.close();table.deleteLater();self.app.processEvents()

    def test_late_native_metrics_are_rechecked_before_pill_paint(self):
        class Pill(QPushButton):
            wanted=94
            def sizeHint(self):return QSize(self.wanted,22)
            def minimumSizeHint(self):return self.sizeHint()
        table=QTableWidget(1,1);table.resize(500,170)
        table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        table.setItem(0,0,QTableWidgetItem('Provider'))
        cell=SourcePillCell();layout=QHBoxLayout(cell);layout.setContentsMargins(4,2,4,2)
        pill=Pill('Provider');layout.addWidget(pill)
        table.setCellWidget(0,0,cell);cell.bind(table,0,0);table.show()
        self.app.processEvents();self.app.processEvents()
        # Native first-exposure/DPR metrics can change after the parent measured
        # the old hint, without a new parent LayoutRequest before painting.
        pill.wanted=101;pill.update()
        for _ in range(4):self.app.processEvents()
        self.assertGreaterEqual(pill.minimumWidth(),101)
        self.assertGreaterEqual(pill.width(),101)
        table.setRowCount(0);self.app.processEvents();table.close();table.deleteLater();self.app.processEvents()


if __name__=='__main__':unittest.main()

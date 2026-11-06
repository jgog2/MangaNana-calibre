"""Qt presentation geometry, model ownership and bounded cover reprioritization."""
import ast
from pathlib import Path
from types import SimpleNamespace as S
from collections import deque
from threading import RLock
from unittest.mock import patch
import unittest
from qt.core import (Qt, QApplication, QFont, QFontMetrics, QSize, QListWidget,
                     QListWidgetItem, QListView, QLabel, QPersistentModelIndex, QScrollArea)
from calibre_plugins.manganana.presentation.hero_readability import synopsis_excerpt, GenreStrip, SynopsisField
from calibre_plugins.manganana.app.workflow_state import HighPriestessState
from calibre_plugins.manganana.books.imaging import cover_rendering as covers

ROOT=Path(__file__).resolve().parents[1]


def method(path, name, scope):
    tree=ast.parse((ROOT/path).read_text(encoding='utf8'))
    fn=next(n for n in ast.walk(tree)if isinstance(n,ast.FunctionDef)and n.name==name)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),scope)
    return scope[name]


class WarmHeroResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance()or QApplication([])

    def test_synopsis_uses_only_complete_lines_and_elides_overflow(self):
        font=QFont();font.setPixelSize(15);fm=QFontMetrics(font)
        text='An intentionally long synopsis with readable whole lines. '*20
        result=synopsis_excerpt(text,font,280,3*fm.lineSpacing())
        self.assertEqual(3,len(result.splitlines()))
        self.assertTrue(result.endswith('\u2026'))
        self.assertTrue(all(fm.horizontalAdvance(line)<=280 for line in result.splitlines()))

    def test_synopsis_handles_native_text_emoji_long_words_and_empty_space(self):
        font=QFont();font.setPixelSize(16);fm=QFontMetrics(font)
        for text in ('進撃の巨人の物語'*30,'Hello \U0001f680 manga '*35,'UnspacedWord'*80):
            result=synopsis_excerpt(text,font,220,4*fm.lineSpacing())
            self.assertLessEqual(len(result.splitlines()),4)
            self.assertTrue(all(fm.horizontalAdvance(line)<=220 for line in result.splitlines()))
            self.assertNotIn('\ufffd',result)
        self.assertEqual('',synopsis_excerpt('Text',font,200,0))
        self.assertEqual('',synopsis_excerpt('',font,200,100))

    def test_unchanged_synopsis_reuses_layout_and_restores_cached_excerpt(self):
        scroll=QScrollArea();label=QLabel();scroll.setWidget(label);scroll.setWidgetResizable(True)
        field=SynopsisField(label,scroll);scroll.resize(320,120);scroll.show();self.app.processEvents()
        with patch('calibre_plugins.manganana.presentation.hero_readability.synopsis_excerpt',wraps=synopsis_excerpt)as fit:
            field.set_text('A repeatable synopsis with enough text. '*20)
            first=label.text();field.set_text(field.text);field.render()
            self.assertEqual(1,fit.call_count)
            label.setText('Legacy full-text refresh');field.render()
            self.assertEqual(first,label.text());self.assertEqual(1,fit.call_count)
        scroll.close();scroll.deleteLater();self.app.processEvents()

    def test_genres_fit_actual_width_and_font_changes(self):
        strip=GenreStrip();strip.set_tags(['Psychological','Science Fiction','Adventure','Historical','Drama'])
        strip.resize(280,40);strip.show();self.app.processEvents()
        for width in (280,120,440):
            strip.resize(width,40);self.app.processEvents()
            for chip in strip.chips+[strip.overflow]:
                if chip.isVisible():
                    self.assertGreaterEqual(chip.width(),chip.sizeHint().width())
                    self.assertLessEqual(chip.geometry().right(),strip.contentsRect().right())
        strip.chips[0].setStyleSheet('font-size:24px;padding:7px 12px;')
        self.app.processEvents()
        for chip in strip.chips+[strip.overflow]:
            if chip.isVisible():self.assertGreaterEqual(chip.width(),chip.sizeHint().width())
        self.assertIn('Science Fiction',strip.toolTip())
        strip.close();strip.deleteLater();self.app.processEvents()

    def test_visible_range_matches_linear_oracle_in_both_directions(self):
        visible=method(Path('presentation/choose_manga_ui.py'),'_visible_row_range',{'QSize':QSize})
        view=QListWidget();view.setFlow(QListView.Flow.LeftToRight);view.setWrapping(False)
        view.resize(650,280);view.setSpacing(5)
        for i in range(1169):
            item=QListWidgetItem(str(i));item.setSizeHint(QSize(172,244));view.addItem(item)
        d=S(volume_list=view,workflow_mode='chapter',fidelity=S(tile_size=QSize(172,244)))
        view.show();self.app.processEvents()
        for direction in (Qt.LayoutDirection.LeftToRight,Qt.LayoutDirection.RightToLeft):
            view.setLayoutDirection(direction);view.doItemsLayout();self.app.processEvents()
            for fraction in (0,.1,.5,1):
                view.horizontalScrollBar().setValue(round(view.horizontalScrollBar().maximum()*fraction))
                self.app.processEvents();area=view.viewport().rect().adjusted(-344,0,344,0)
                expected=[i for i in range(view.count())if view.visualItemRect(view.item(i)).intersects(area)]
                expected=range(min(expected),max(expected)+1)if expected else range(5)
                with patch.object(view,'visualItemRect',wraps=view.visualItemRect)as rect:
                    self.assertEqual(list(expected),list(visible(d,view,72,2)))
                    self.assertLessEqual(rect.call_count,32)
        view.close();view.deleteLater();self.app.processEvents()

    def test_card_ownership_survives_sort_and_rejects_removed_widgets(self):
        live=method(Path('presentation/choose_manga_ui.py'),'_live_inventory_items',{'Qt':Qt,'VolumeRowWidget':QLabel})
        view=QListWidget();d=S(volume_list=view)
        for value in ('c','a','b'):
            item=QListWidgetItem(value);view.addItem(item);row=QLabel(value);view.setItemWidget(item,row)
            row._inventory_model_index=QPersistentModelIndex(view.indexFromItem(item))
        view.sortItems();self.assertEqual({'a','b','c'},{item.text()for item in live(d)})
        view.removeItemWidget(view.item(0))
        self.assertEqual({'b','c'},{item.text()for item in live(d)})
        view.clear();self.assertEqual([],live(d))
        view.deleteLater();self.app.processEvents()

    def test_duplicate_projection_does_not_clear_selection(self):
        state=HighPriestessState(mode='chapter')
        generation=state.select_provider(dict(source_id='mangadex',id='exact'))
        state.begin_chapter_preparation(generation,7)
        state.settle_chapter_acquisition(generation,7,'ready',({'id':'a','chapter':'1'},))
        state.settle_publication_structure(generation,'valid')
        rows=({'id':'a','chapter':'1','volume':'1'},)
        self.assertTrue(state.freeze_chapter_projection(generation,7,('projection',),rows))
        state.set_inventory_selection(('a',))
        self.assertFalse(state.freeze_chapter_projection(generation,7,('projection',),rows))
        self.assertEqual(frozenset(('a',)),state.inventory_selection)
        self.assertFalse(state.freeze_chapter_projection(generation,7,('new projection',),rows))
        self.assertTrue(state.begin_chapter_preparation(generation,8))
        state.settle_chapter_acquisition(generation,8,'ready',({'id':'a','chapter':'1'},))
        self.assertTrue(state.freeze_chapter_projection(generation,8,('new projection',),rows))
        self.assertFalse(state.freeze_chapter_projection(generation-1,7,('stale',),rows))

    def test_pending_thumbnails_can_be_replaced_without_repeating_active_request(self):
        scope={};take=method(Path('app/main.py'),'_next_entry',scope)
        prioritize=method(Path('app/main.py'),'prioritize',scope)
        worker=S(_entry_lock=RLock(),_pending_entries=[('old0',),('old1',)],_active_entry=None,
                 _recent_entries=deque(maxlen=8),_entry_queue_closed=False,isInterruptionRequested=lambda:False)
        self.assertEqual(('old0',),take(worker))
        self.assertTrue(prioritize(worker,[('old0',),('new0',),('new0',),('new1',)]))
        self.assertEqual(('new0',),take(worker));self.assertEqual(('new1',),take(worker))
        self.assertIsNone(take(worker));self.assertFalse(prioritize(worker,[('late',)]))

    def test_decoded_templates_are_bounded_immutable_and_independently_owned(self):
        covers._template_pixels.cache_clear()
        first=covers._art('background.png');expected=first.tobytes();first.paste('red',(0,0,40,40))
        self.assertEqual(expected,covers._art('background.png').tobytes())
        covers._art('stamp.png')
        self.assertEqual(2,covers._template_pixels.cache_info().currsize)
        size,pixels=covers._template_pixels(covers._resource('background.png'))
        self.assertIsInstance(pixels,bytes);self.assertEqual(size[0]*size[1]*4,len(pixels))
        covers._template_pixels.cache_clear()

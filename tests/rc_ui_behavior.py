"""Behavioral replacements for retired High Priestess source-string contracts.

Run under Calibre Python with a disposable CALIBRE_CONFIG_DIRECTORY. Native
installed-ZIP tests additionally exercise actual provider/preview/import workers.
"""
import gc,sys,types
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace

_application=None

@contextmanager
def dialog():
    global _application
    from qt.core import QApplication,QWidget,QIcon,QCoreApplication,QEvent
    root=Path(__file__).resolve().parents[1]
    if 'calibre_plugins.manganana' not in sys.modules:
        package=types.ModuleType('calibre_plugins.manganana');package.__path__=[str(root)]
        sys.modules['calibre_plugins.manganana']=package
    from calibre_plugins.manganana.presentation.choose_manga_ui import ChooseMangaDialog
    app=QApplication.instance() or QApplication([]);_application=app
    gui=QWidget();gui.current_db=SimpleNamespace(new_api=SimpleNamespace(all_book_ids=lambda:()),library_path='C:/MangaNana-Dev/Test-Library',library_id='ui-behavior-test')
    d=ChooseMangaDialog(gui,QIcon())
    try:
        d.resize(1672,941);d.show();app.processEvents()
        yield d,app
    finally:
        d.reject();d.setParent(None);d.deleteLater();gui.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();gc.collect()

def assert_contract(test,name):
    if name in ('confident_provider_group_seeds_provider_independent_publication_identity',
                'reference_lookup_uses_selected_work_not_raw_search_box_text',
                'search_waits_for_terminal_enrichment_and_consolidates_work_facts_before_render'):
        from tests.test_patch1c_publication import family
        from calibre_plugins.manganana.metadata.reference_integration import canonical_family_publication_context
        a,b=family('mangapill'),family('atsu');before=[dict(a),dict(b)]
        first=canonical_family_publication_context(a,[a,b],'original')
        second=canonical_family_publication_context(b,[b,a],'original')
        test.assertTrue(first.shareable);test.assertEqual(first.reference_key,second.reference_key)
        test.assertEqual(before,[a,b]);test.assertIn('JoJolion',first.canonical_title)
        bad=dict(b,edition='official_color')
        test.assertNotEqual(first.reference_key,canonical_family_publication_context(bad,[a,bad],'official_color').reference_key)
        return
    with dialog() as (d,app):
        from qt.core import QGroupBox,QDialogButtonBox,Qt,QLabel,QPushButton
        from calibre_plugins.manganana.app import main
        if name in ('three_stage_header_and_stacked_body_contract','judgement_header_is_shared_and_updates_from_workflow_state'):
            test.assertEqual(3,d.stage_stack.count());test.assertIs(d.header,d.anka_shell.header)
            for i,stage in enumerate(('choose_manga','book_customization','finalization')):
                d._set_stage(stage);app.processEvents()
                test.assertEqual(i,d.stage_stack.currentIndex());test.assertEqual(stage,d.header.stepper.active_stage)
                test.assertEqual(stage=='finalization',not d.download_btn.isHidden())
        elif name=='all_stages_share_one_center_gutter_and_stage_one_geometry_is_fixed':
            geometry=[]
            for mode in ('volume','chapter','import','volume'):
                d._set_workflow_mode(mode);app.processEvents()
                geometry.append((d.volume_mode_btn.parentWidget().geometry().getRect(),d.header.geometry().getRect()))
                test.assertEqual(0,d.anka_shell.workspace.verticalScrollBar().maximum())
            test.assertTrue(all(g==geometry[0] for g in geometry),geometry)
        elif name in ('book_customization_owns_layout_and_inline_live_preview','live_preview_is_explicit_portrait_and_landscape_capable'):
            d._set_stage('book_customization');app.processEvents()
            test.assertFalse(d.pairing_preview_btn.isHidden())
            test.assertTrue(d.live_preview_scroll.isHidden(),'Empty preview has no image tiles')
            for button,layout in ((d.portrait_btn,'original_pages'),(d.landscape_btn,'paired_landscape')):
                button.click();test.assertEqual(layout,d.page_layout.currentData());test.assertTrue(button.isChecked())
            test.assertFalse(d.pairing_preview_btn.isEnabled(),'No selected acquisition may fetch a preview')
        elif name=='bulk_metadata_is_pending_until_one_explicit_apply':
            d._set_applied_metadata('Original','Author','Series')
            d.preview_data={'rows':[], 'selected_download_count':0};d.title.setText('Edited');test.assertTrue(d._metadata_pending)
            test.assertEqual('Original',d._applied_metadata_values()[0])
            d.apply_metadata();test.assertFalse(d._metadata_pending)
            test.assertEqual('Edited',d._applied_metadata_values()[0])
        elif name=='final_outputs_keep_pages_size_and_separate_use_control':
            headers=[d.preview_table.horizontalHeaderItem(i).text() for i in range(d.preview_table.columnCount())]
            test.assertEqual(['Use','Cover','Format','Series #','Title','Source','Pages','Status'],headers)
            test.assertEqual(Qt.FocusPolicy.StrongFocus,d.preview_table.focusPolicy())
            test.assertFalse(d.download_btn.isEnabled())
        elif name=='metadata_fields_are_wide_and_page_clicks_can_clear_focus':
            d._set_stage('finalization');app.processEvents()
            for width in (1280,1672):
                d.resize(width,941);app.processEvents()
                for field in (d.title,d.author,d.series):
                    test.assertGreater(field.width(),field.fontMetrics().horizontalAdvance('Typical manga title'))
                    test.assertLessEqual(field.geometry().right(),field.parentWidget().width())
            d.title.setFocus();app.processEvents();test.assertTrue(d.title.hasFocus())
            owner=d.title.parentWidget()
            while owner and not isinstance(owner,main.FocusClearingFrame):owner=owner.parentWidget()
            test.assertIsNotNone(owner);owner.setFocus(Qt.FocusReason.MouseFocusReason);test.assertFalse(d.title.hasFocus())
        elif name=='ordinary_control_hover_descriptions_are_removed':
            test.assertEqual('',d.search_btn.toolTip());test.assertEqual('',d.load_btn.toolTip())
            test.assertTrue(d.renumber_outputs_btn.toolTip(),'Destructive/editor actions retain useful guidance')
        elif name in ('preferences_spacing_name_and_modal_buttons','enrichment_preferences_are_separate_from_manga_sources'):
            prefs=main.PreferencesDialog(d)
            try:
                names=[g.title() for g in prefs.findChildren(QGroupBox)]
                test.assertIn('Search Enrichment',names);test.assertIn('Search Metadata Cache',names)
                buttons=prefs.findChild(QDialogButtonBox);test.assertIsNotNone(buttons)
                test.assertIsNotNone(buttons.button(QDialogButtonBox.StandardButton.Ok))
                test.assertIsNotNone(buttons.button(QDialogButtonBox.StandardButton.Cancel))
                sources=main.MangaSourcesDialog(main.SOURCE_REGISTRY,main.prefs,d)
                try:
                    labels=' '.join(w.text() for w in sources.findChildren(QLabel))
                    test.assertNotIn('AniList',labels);test.assertNotIn('Kitsu',labels)
                finally:sources.reject();sources.deleteLater()
            finally:prefs.reject();prefs.deleteLater()
        elif name=='reference_worker_is_cancellation_aware_and_current_callback_refreshes_covers':
            d._reference_request_id=9;before=dict(d._loaded_covers)
            d._on_reference_lookup_ready({'request_id':8,'generation':d.workflow_state.selected_record_load_generation})
            test.assertEqual(before,d._loaded_covers)
            class Worker:
                cancelled=False
                def requestInterruption(self):self.cancelled=True
                def isRunning(self):return True
            w=Worker();d._reference_worker=w
            try:d._reset_reference_lookup()
            finally:d._reference_worker=None
            test.assertTrue(w.cancelled);test.assertIsNone(d._reference_worker)
            # Current-result artwork merge order is exercised by CoverRepairTests.
        elif name=='search_qualification_is_bounded_generation_guarded_and_keeps_provider_cards':
            before=dict(d._search_resolutions)
            d._on_search_resolution({'request_id':d._search_resolution_request_id},d.workflow_mode,d._mode_generation-1)
            test.assertEqual(before,d._search_resolutions)
            d._begin_close()
            d._on_search_resolution({'request_id':d._search_resolution_request_id},d.workflow_mode,d._mode_generation)
            test.assertEqual(before,d._search_resolutions)
            test.assertLessEqual(main.SEARCH_QUALIFICATION_LIMIT,main.SEARCH_RESOLUTION_LIMIT)
        elif name=='existing_book_policy_distinguishes_skip_and_replacement_work':
            previous=main.prefs['duplicate_policy'];calls=[]
            d.existing_volumes=lambda *a:(calls.append(a) or {5.0})
            try:
                for policy,expected in (('skip',({5.0},set())),('replace',(set(),{5.0}))):
                    main.prefs['duplicate_policy']=policy
                    test.assertEqual(expected,d.effective_existing_for_policy('Fixture',{'exact-key'},'pdf'))
                    test.assertEqual(('Fixture',{'exact-key'},'pdf'),calls[-1])
                    test.assertEqual(policy=='replace',d._session_replace_existing)
            finally:main.prefs['duplicate_policy']=previous
        elif name=='chapter_output_mode_controls_are_explicit':
            test.assertEqual(['detected_volumes','manual_volumes','individual_chapters'],[d.chapter_output_combo.itemData(i) for i in range(d.chapter_output_combo.count())])
            d.chapter_mode_btn.click();test.assertFalse(d.chapter_output_widget.isHidden())
            test.assertEqual('individual_chapters',d.chapter_output_combo.currentData())
            d.volume_mode_btn.click();test.assertTrue(d.chapter_output_widget.isHidden())
        else:raise AssertionError('Missing replacement behavior: '+name)

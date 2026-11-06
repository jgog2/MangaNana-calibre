from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parents[1]
MAIN=ROOT.joinpath('app/main.py').read_text(encoding='utf-8')
WIDGETS=ROOT.joinpath('presentation/mangaanka_widgets.py').read_text(encoding='utf-8')
PLUGIN=ROOT.joinpath('__init__.py').read_text(encoding='utf-8')


def section(start,end):
    begin=MAIN.index(start)
    return MAIN[begin:MAIN.index(end,begin)]


class HighPriestessUiContracts(unittest.TestCase):
    def test_three_stage_header_and_stacked_body_contract(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'three_stage_header_and_stacked_body_contract')

    def test_judgement_header_is_shared_and_updates_from_workflow_state(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'judgement_header_is_shared_and_updates_from_workflow_state')

    def test_choose_manga_starts_generic_and_has_no_volume_range_ui(self):
        build=section('def build_ui(self):','# BOOK CUSTOMIZATION:')
        self.assertIn("self.inventory_heading=self.heading('Manga')",build)
        self.assertIn("self.mode_helper=QLabel('Choose Volumes, Chapters, or Import to begin.')",build)
        self.assertIn("QPushButton('Select All')",build)
        self.assertIn("QPushButton('Clear')",build)
        self.assertNotIn('Select a Volume Range',build)
        self.assertNotIn("setPlaceholderText('From')",build)
        self.assertNotIn("setPlaceholderText('To')",build)
        self.assertNotIn('Use Entire Series',build)

    def test_discovery_is_compact_and_results_are_dominant(self):
        build=section('def build_ui(self):','# BOOK CUSTOMIZATION:')
        self.assertIn("QLabel('Search')",build)
        self.assertIn("QLabel('Mode')",build)
        self.assertIn("QLabel('Direct Link')",build)
        self.assertIn("self.load_btn = QPushButton('Load')",build)
        self.assertIn('self.search_results.setMinimumHeight(300)',build)
        self.assertNotIn('Already have a manga link?',build)
        self.assertNotIn("QLabel('or')",build)

    def test_mode_change_preserves_query_without_automatic_network_replay(self):
        mode=section('def _set_workflow_mode(self, mode):','def _choose_layout(')
        self.assertIn('self.workflow_state.change_mode(mode)',mode)
        self.assertIn('self.search_results.clear()',mode)
        self.assertIn('Mode changed to',mode)
        self.assertNotIn('search_mangadex(',mode)
        self.assertNotIn('load_metadata(',mode)

    def test_stage_one_footer_is_mode_aware_and_not_final_output_bound(self):
        actions=section('def _update_workflow_actions(self):','def _has_volume_selection(')
        self.assertIn("self.workflow_hint.setText('Choose Volumes, Chapters, or Import to begin.')",actions)
        self.assertIn("noun='chapter' if self.workflow_mode == 'chapter' else 'volume'",actions)
        choose=actions[:actions.index("if stage == 'book_customization':")]
        self.assertNotIn('selected_download_count',choose)
        self.assertNotIn('Review',actions)

    def test_upstream_invalidation_never_prepares_or_shows_finalization(self):
        invalidation=section('def invalidate_preview(self, *args):','def _bulk_metadata_changed(')
        self.assertIn('self.workflow_state.invalidate_downstream()',invalidation)
        self.assertNotIn('continue_preview(',invalidation)
        self.assertNotIn('_set_stage(',invalidation)
        self.assertNotIn('.setCurrentWidget(',invalidation)
        self.assertNotIn('QTimer.singleShot',invalidation)

    def test_explicit_next_is_the_only_upstream_finalization_preparation(self):
        advance=section('def _advance_stage(self):','def _back_stage(')
        self.assertIn("self._set_stage('book_customization')",advance)
        self.assertIn("self._set_stage('finalization')",advance)
        self.assertEqual(1,advance.count('self.continue_preview()'))
        first_transition=advance[:advance.index("if self.workflow_state.stage == 'book_customization':")]
        self.assertNotIn('continue_preview',first_transition)
        back=section('def _back_stage(self):','def _clear_active_provider_selection(')
        self.assertNotIn('continue_preview',back)

    def test_book_customization_owns_layout_and_inline_live_preview(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'book_customization_owns_layout_and_inline_live_preview')

    def test_live_preview_is_explicit_portrait_and_landscape_capable(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'live_preview_is_explicit_portrait_and_landscape_capable')

    def test_live_preview_renders_inline_and_guards_late_work(self):
        preview=section('def on_pairing_preview_progress(','def maybe_offer_virtual_library(')
        self.assertIn('request_id != self._live_preview_request_id',preview)
        self.assertIn("self.workflow_state.stage != 'book_customization'",preview)
        self.assertIn('self.live_preview_grid.addWidget(',preview)
        self.assertIn('self.workflow_state.mark_preview_ready()',preview)
        self.assertNotIn('.exec()',preview)

    def test_finalization_owns_creation_metadata_and_outputs(self):
        build=section('# FINALIZATION:','# Provider-search progress')
        self.assertIn("self.heading('Book Creation & Metadata')",build)
        self.assertIn("self.heading('Final Outputs')",build)
        self.assertIn("metadata_form.addRow('Title',self.title)",build)
        self.assertIn("metadata_form.addRow('Series',self.series)",build)
        self.assertIn("metadata_form.addRow('Author',self.author)",build)
        self.assertIn('self.chapter_output_widget',build)
        self.assertNotIn("addRow('Language'",build)

    def test_bulk_metadata_is_pending_until_one_explicit_apply(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'bulk_metadata_is_pending_until_one_explicit_apply')

    def test_final_outputs_keep_pages_size_and_separate_use_control(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'final_outputs_keep_pages_size_and_separate_use_control')

    def test_search_contracts_remain_explicit_and_provider_local(self):
        prefer=section('def _prefer_colored_changed(self, checked):','def _search_score(')
        self.assertIn('_render_provider_search_results()',prefer)
        self.assertNotIn('search_mangadex(',prefer)
        finish=section('def _finish_coordinated_search(self):','def _find_search_item(')
        self.assertIn('if not self._search_display_barrier.complete:',finish)
        self.assertIn('self._render_provider_search_results()',finish)
        self.assertIn('not self._enrichment_received',finish)

    def test_ratings_are_secondary_metadata_not_title_text(self):
        row=section('class SearchResultRowWidget(QFrame):','class ManualChapterVolumeDialog(QDialog):')
        self.assertIn('self.title_label=QLabel(self._base_title)',row)
        self.assertIn('rating_text=format_rating_label(rating)',row)
        self.assertIn('self.rating_label=QLabel(rating_text)',row)
        build=section('def build_ui(self):','def _set_stage(')
        self.assertIn("self.selected_rating=QLabel('')",build)
        loaded=section('def _apply_loaded_manga(','def _download_language_changed(')
        self.assertIn('selected_rating=format_rating_label(',loaded)
        self.assertIn("get('rating_display'))",loaded)

    def test_all_stages_share_one_center_gutter_and_stage_one_geometry_is_fixed(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'all_stages_share_one_center_gutter_and_stage_one_geometry_is_fixed')

    def test_inherited_layout_recomputes_live_preview_eligibility_on_stage_entry(self):
        stages=section('def _set_stage(self, stage):','def _set_cancel_action(')
        book_branch=stages[stages.index("if stage == 'book_customization':"):]
        self.assertIn('self._update_live_preview_action()',book_branch)
        eligibility=section('def _update_live_preview_action(self, focused_change=False):','def open_pairing_preview(')
        self.assertIn('target=self._preview_sample_target()',eligibility)
        self.assertIn('self.pairing_preview_btn.setEnabled(bool(target))',eligibility)
        signature=section('def _live_preview_signature_value(self):','def _reset_live_preview(')
        self.assertIn('self.page_layout.currentData()',signature)

    def test_inventory_and_final_outputs_use_shared_provider_pills(self):
        volume=section('class VolumeRowWidget(QFrame):','_PROVIDER_ICON_PIXMAPS = {}')
        self.assertIn('ProviderBadgeWidget(provider_spec,self,effects=False)',volume)
        rebuild=section('def _rebuild_volume_list(self):','def _load_visible_volume_thumbs(')
        self.assertIn('provider_spec=provider_badge_spec(',rebuild)
        final=section('def _final_output_source_widget(self,row):','def on_preview_ready(')
        self.assertIn('ProviderBadgeWidget(provider_badge_spec(',final)

    def test_existing_book_policy_distinguishes_skip_and_replacement_work(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self,'existing_book_policy_distinguishes_skip_and_replacement_work')

    def test_final_output_cover_decoration_is_cache_only(self):
        cover=section('def _planned_output_cover_url(self,row):','def _final_output_source_widget(self,row):')
        self.assertIn("resolve_group_cover_url(",cover)
        self.assertIn("group.get('chapters') or ()",cover)
        self.assertIn("thumbnail=row.get('cover_thumbnail')",cover)
        self.assertIn('pixmap.scaled(44,62',cover)
        for forbidden in ('ImageBatchWorker(', 'get_cover', 'get_page_manifest', 'urlopen'):
            self.assertNotIn(forbidden,cover)

    def test_metadata_labels_color_badges_calibre_tags_and_ampersand_are_consistent(self):
        self.assertIn("'Description: '",MAIN)
        render=section('def _render_provider_search_results(self):','def _render_canonical_search_results(self, final=False):')
        self.assertIn("primary['badge']=primary.get('badge') or edition_display_label(primary)",render)
        self.assertIn("QPushButton('Download && Add to Calibre')",MAIN)
        self.assertIn("mi.tags = list(self._calibre_work_tags())",MAIN)
        replacement=section('def _replace_existing_book(self, book_id, item, author, series, language):','def show_manganana_library(self):')
        self.assertIn("'tags': {book_id: list(self._calibre_work_tags(self._existing_calibre_tags(book_id)))}",replacement)

    def test_canonical_creator_and_cover_refresh_reach_active_ui_paths(self):
        enrichment=section('def _apply_late_search_enrichment(self, render=True):','def _on_enrichment_ready(')
        self.assertIn('if selected_key == key:',enrichment)
        self.assertIn("'canonical_author':row.get('canonical_author') or ''",enrichment)
        selected=section('def _apply_work_level_enrichment(self, metadata, overlay):','def _apply_selected_enrichment(self, overlay):')
        self.assertIn("canonical_author=str(overlay.get('canonical_author') or '').strip()",selected)
        image_store=section('def _store_image_bytes(self, url, raw):','def _load_visible_search_thumbs(self):')
        self.assertIn('self._failed_image_urls.discard(url)',image_store)
        search_ready=section('def _on_search_thumb_ready(self, data):','def _on_search_thumb_failed(self, data):')
        self.assertIn('self._store_image_bytes(url,raw)',search_ready)
        search=section('def search_mangadex(self, reset=True, expected_generation=None):','def _on_search_ready(')
        self.assertIn('self._failed_image_urls.clear()',search)

    def test_warm_search_cache_reenters_thumbnail_recovery_lifecycle(self):
        search=section('def search_mangadex(self, reset=True, expected_generation=None):','def _on_search_ready(')
        clear_at=search.index('self._failed_image_urls.clear()')
        cache_at=search.index('get_query_snapshot(')
        warm_at=search.index("snapshot.get('final')")
        retry_at=search.index('QTimer.singleShot(0,self._load_visible_search_thumbs)',warm_at)
        self.assertLess(clear_at,cache_at)
        self.assertLess(warm_at,retry_at)
        self.assertIn('self._search_raw_results=list(final_search_records(snapshot))',search)
        self.assertIn('self._render_provider_search_results()',search[warm_at:retry_at])
        loader=section('def _load_visible_search_thumbs(self):','def _on_search_thumb_ready(self, data):')
        self.assertIn("if not url:\n                continue",loader)
        self.assertIn('self.search_thumb_worker.isRunning()',loader)
        self.assertIn('elif url not in queued_urls and len(batch) < COVER_BATCH_LIMIT:',loader)
        self.assertNotIn("not info.get('thumb_requested')",loader)
        image_store=section('def _store_image_bytes(self, url, raw):','def _load_visible_search_thumbs(self):')
        self.assertIn('self._failed_image_urls.discard(url)',image_store)
        self.assertIn('self._scaled_pixmap_cache.pop(key,None)',image_store)

    def test_metadata_fields_are_wide_and_page_clicks_can_clear_focus(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'metadata_fields_are_wide_and_page_clicks_can_clear_focus')

    def test_prefer_colored_uses_custom_selection_treatment_without_searching(self):
        selection=section('class MangaSelectionCheckBox(QCheckBox):','class PreviewUseSelector(QPushButton):')
        self.assertIn('QStyleOptionButton()',selection)
        self.assertIn('painter.drawEllipse(rect.adjusted(1,1,-1,-1))',selection)
        self.assertIn("painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,'\u2713')",selection)
        build=section('def build_ui(self):','def _set_stage(')
        self.assertIn("self.prefer_colored = MangaSelectionCheckBox('Prefer Colored')",build)
        self.assertIn("self.prefer_colored.setObjectName('mangaSelectionToggle')",build)
        prefer=section('def _prefer_colored_changed(self, checked):','def _search_score(')
        self.assertNotIn('search_mangadex(',prefer)

    def test_inventory_reuses_existing_covers_and_selected_card_surfaces_metadata(self):
        cover=section('def _chapter_inventory_cover_url(self, chapter):','def _rebuild_volume_list(self):')
        self.assertIn("chapter.get('_publication_cover_url')",cover)
        self.assertIn("chapter.get('cover_url')",cover)
        self.assertIn('(self._loaded_covers or {}).get(volume)',cover)
        self.assertIn("return self._main_cover_url or ''",cover)
        self.assertNotIn('ImageBatchWorker(',cover)
        selected=section('def _set_selected_optional_text(','def _provider_url_for_source(')
        self.assertIn("metadata.get('description')",selected)
        self.assertIn("metadata.get('alternate_titles')",selected)
        self.assertIn("metadata.get('tags')",selected)
        self.assertIn('self._set_selected_inventory_count(',MAIN)

    def test_chapter_rows_preserve_exact_artwork_identity_for_async_callbacks(self):
        rebuild=section('def _rebuild_volume_list(self):','def _load_visible_volume_thumbs(')
        self.assertIn('artwork_identity=self._chapter_inventory_artwork_identity(chapter,cover_url)',rebuild)
        self.assertIn("'cover_url':cover_url,'artwork_identity':artwork_identity",rebuild)
        identity=section('def _chapter_inventory_artwork_identity(chapter, cover_url):','def _rebuild_volume_list(self):')
        self.assertIn("chapter.get('_publication_cover_identity')",identity)
        callback=section('def _on_volume_thumb_ready(self, data):','def _on_volume_thumb_failed(self, data):')
        self.assertIn('self._row_accepts_artwork_callback(info,url)',callback)

    def test_chapter_first_render_waits_for_terminal_structure_without_timer(self):
        load=section('def _load_volume_plan(self, force=False):','def _on_volume_plan_ready(self, data):')
        self.assertIn('begin_chapter_preparation(',load)
        self.assertIn("self._set_chapter_preparing('Preparing chapters…')",load)
        self.assertNotIn('singleShot(1000',load)
        acquisition=section('def _apply_chapter_plan(self, request_id, language, chapters):','def _on_volume_plan_failed(self, data):')
        self.assertIn('settle_chapter_acquisition(',acquisition)
        self.assertIn('_try_finalize_chapter_projection()',acquisition)
        self.assertNotIn('self._rebuild_volume_list()',acquisition)
        freeze=section('def _try_finalize_chapter_projection(self, prepared_projection=None):','def _reset_reference_lookup(self):')
        self.assertIn('freeze_chapter_projection(',freeze)
        self.assertLess(freeze.index('freeze_chapter_projection('),freeze.index('self._rebuild_volume_list()'))
        self.assertIn('self.volume_list.setEnabled(self._download_language_valid)',freeze)

    def test_selected_provider_badge_is_not_replaced_by_acquisition_fallback(self):
        fallback=section('def _on_selected_fallback_ready(self, payload, selected_key, mode, generation):','def _start_inventory_comparison(')
        self.assertNotIn('self._set_selected_source_badge(*self._active_fallback_source',fallback)
        self.assertIn('Selected provider:',fallback)
        loaded=section('def _apply_loaded_manga(self, request_id, data):','def _download_language_changed(')
        self.assertIn('self._set_selected_source_badge(self.current_source_id,self.current_source.display_name',loaded)

    def test_search_qualification_is_bounded_generation_guarded_and_keeps_provider_cards(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'search_qualification_is_bounded_generation_guarded_and_keeps_provider_cards')

    def test_confident_provider_group_seeds_provider_independent_publication_identity(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'confident_provider_group_seeds_provider_independent_publication_identity')

    def test_live_search_renderer_uses_presentation_creator_not_provider_raw_creator(self):
        render=section('def _render_provider_search_results(self):','def _render_canonical_search_results(')
        self.assertIn("primary.get('title') or 'Untitled',primary.get('author') or ''",render)
        enrichment=section('def _apply_late_search_enrichment(self, render=True):','def _on_enrichment_ready(')
        self.assertIn("merged.get('title') or '',merged.get('author') or ''",enrichment)

    def test_search_waits_for_terminal_enrichment_and_consolidates_work_facts_before_render(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'search_waits_for_terminal_enrichment_and_consolidates_work_facts_before_render')

    def test_projection_diagnostic_reports_composition_without_wikipedia_overclaim(self):
        projection=section('def _log_publication_projection(self, projection):','def _try_finalize_chapter_projection(')
        self.assertIn('Provider explicit:',projection)
        self.assertIn('Reference explicit:',projection)
        self.assertIn('Derived pre-Chapter-1:',projection)
        reference=section('def _on_reference_lookup_ready(self, payload):','def _calibre_work_tags(')
        self.assertNotIn('explicit chapter mappings and',reference)

    def test_chapter_bulk_selection_batches_repaints_and_downstream_refresh(self):
        bulk=section('def _restyle_inventory_rows(self):','def _checked_volume_values(self):')
        self.assertIn('self.volume_list.setUpdatesEnabled(False)',bulk)
        self.assertIn('self.volume_list.viewport().update()',bulk)
        clear=section('def _clear_inventory_selection(self):','def _select_all_inventory(self):')
        select=section('def _select_all_inventory(self):','def _use_entire_series(self):')
        self.assertIn('self._restyle_inventory_rows()',clear)
        self.assertIn('self._restyle_inventory_rows()',select)
        self.assertEqual(1,clear.count('self._refresh_chapter_output_options()'))
        self.assertEqual(1,select.count('self._refresh_chapter_output_options()'))

    def test_ordinary_control_hover_descriptions_are_removed(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'ordinary_control_hover_descriptions_are_removed')

    def test_preferences_spacing_name_and_modal_buttons(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'preferences_spacing_name_and_modal_buttons')

    def test_plugin_metadata_exact_contract(self):
        self.assertIn("author = 'jgog'",PLUGIN)
        self.assertIn('description = "Reading manga shouldn\'t turn into a damn IT project."',PLUGIN)

    def test_reference_lookup_uses_selected_work_not_raw_search_box_text(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'reference_lookup_uses_selected_work_not_raw_search_box_text')

    def test_reference_worker_is_cancellation_aware_and_current_callback_refreshes_covers(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'reference_worker_is_cancellation_aware_and_current_callback_refreshes_covers')

    def test_bookwalker_log_and_volume_hint_use_neutral_current_inventory_copy(self):
        handler=section('def _on_reference_lookup_ready(self, payload):','def _calibre_work_tags(')
        self.assertIn('exact volume covers',handler)
        self.assertNotIn('exact standard covers',handler)
        self.assertIn('raw catalog complete; canonical catalog rejected',handler)
        self.assertIn('Google Books artwork lookup unavailable: no API key configured.',handler)
        self.assertIn('Google Books artwork fallback disabled by configuration.',handler)
        self.assertIn('unavailable_publication_context',handler)
        self.assertIn('no_compatible_exact_covers',handler)
        self.assertNotIn('disabled or API key unavailable',handler)
        actions=section('def _update_volume_selection_hint(self):','def _clear_inventory_selection(')
        self.assertIn('volume_selection_hint(has_numbered,has_standalone)',actions)
        self.assertNotIn("'volumes' not in self.current_source.capabilities",actions)


if __name__ == '__main__':
    unittest.main()

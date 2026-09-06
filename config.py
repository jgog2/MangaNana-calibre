from calibre.utils.config import JSONConfig

prefs = JSONConfig('plugins/manganana')
prefs.defaults['ask_virtual_library'] = True
prefs.defaults['include_volume_covers'] = True
prefs.defaults['cover_mode'] = 'keep'
prefs.defaults['zero_pad'] = True
prefs.defaults['language'] = 'en'

prefs.defaults['show_completion_summary'] = True

prefs.defaults['ui_language'] = 'system'

prefs.defaults['duplicate_policy'] = 'skip'

prefs.defaults['page_layout'] = 'original_pages'
prefs.defaults['reading_direction'] = 'rtl'

prefs.defaults['kobo_safe_area_border'] = False
prefs.defaults['show_adult_search_results'] = False
prefs.defaults['source_enabled'] = {}
prefs.defaults['ask_equivalent_sources'] = False
prefs.defaults['search_enrichment'] = True
prefs.defaults['prefer_colored'] = False
prefs.defaults['processing_presets'] = {}

# UI session restoration
prefs.defaults['session_search']=''
prefs.defaults['session_url']=''
prefs.defaults['session_start']=''
prefs.defaults['session_end']=''
prefs.defaults['session_layout']=''
# Missing dimensions select window_geometry.DEFAULT_WINDOW_FRAME. Stored client
# dimensions from existing installations are deliberately not migrated.
prefs.defaults['window_w']=None
prefs.defaults['window_h']=None

# The Emperor: container preference is independent of page processing.
prefs.defaults['output_format'] = 'cbz'

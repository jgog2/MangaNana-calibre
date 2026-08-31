from calibre.utils.config import JSONConfig

prefs = JSONConfig('plugins/manganana')
prefs.defaults['ask_virtual_library'] = True
prefs.defaults['include_volume_covers'] = True
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

# UI session restoration
prefs.defaults['session_search']=''
prefs.defaults['session_url']=''
prefs.defaults['session_start']=''
prefs.defaults['session_end']=''
prefs.defaults['session_layout']=''
prefs.defaults['window_w']=1450
prefs.defaults['window_h']=850

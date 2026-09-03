"""Pure state contracts for the High Priestess three-stage workflow."""

from dataclasses import dataclass, field


STAGES = ('choose_manga', 'book_customization', 'finalization')
TERMINAL_PROVIDER_STATES = frozenset({'success', 'failure', 'timeout', 'cancelled'})
TERMINAL_ACQUISITION_STATES = frozenset({'ready', 'terminal_failure'})
TERMINAL_STRUCTURE_STATES = frozenset({'valid', 'valid_stale', 'unsupported', 'terminal_failure'})


def provider_identity(record):
    row = dict(record or {})
    source_id = str(row.get('source_id') or '')
    item_id = str(row.get('id') or row.get('url') or '')
    return (source_id, item_id) if source_id and item_id else None


def volume_selection_hint(has_numbered, has_standalone):
    if has_numbered and has_standalone:
        return 'Select at least one volume or Standalone Chapters to continue.'
    if has_numbered:
        return 'Select at least one volume to continue.'
    if has_standalone:
        return 'Select Standalone Chapters to continue.'
    return 'Select at least one volume to continue.'


@dataclass
class HighPriestessState:
    stage: str = 'choose_manga'
    pending_query_text: str = ''
    executed_query: str = ''
    mode: str = ''
    download_language: str = 'en'
    prefer_colored: bool = False
    enabled_sources: tuple = ()
    provider_search_states: dict = field(default_factory=dict)
    visible_provider_results: tuple = ()
    selected_provider_record: object = None
    loaded_inventory: tuple = ()
    publication_manifest: object = None
    publication_projection: object = None
    chapter_preparation_generation: int = 0
    chapter_acquisition_state: str = 'idle'
    chapter_structure_state: str = 'idle'
    pending_chapter_inventory: tuple = ()
    chapter_presentation_frozen: bool = False
    volume_preparation_generation: int = 0
    volume_acquisition_state: str = 'idle'
    publication_resolution_state: str = 'idle'
    volume_inventory_final: bool = False
    volume_native_count: int = 0
    volume_derived_count: int = 0
    volume_standalone_count: int = 0
    inventory_selection: frozenset = frozenset()
    search_generation: int = 0
    selected_record_load_generation: int = 0
    finalization_stale: bool = True
    finalization_plan: tuple = ()
    finalization_generation: int = 0
    preview_state: str = 'off'
    preview_stale: bool = False

    def set_pending_query(self, text):
        self.pending_query_text = str(text or '')

    def execute_search(self, enabled_sources):
        self.search_generation += 1
        self.executed_query = self.pending_query_text.strip()
        self.enabled_sources = tuple(str(value) for value in enabled_sources or ())
        self.provider_search_states = {source_id: 'searching' for source_id in self.enabled_sources}
        self.visible_provider_results = ()
        self.clear_selection()
        return self.search_generation

    def settle_provider(self, generation, source_id, status):
        if generation != self.search_generation or status not in TERMINAL_PROVIDER_STATES:
            return False
        if source_id not in self.provider_search_states:
            return False
        self.provider_search_states[source_id] = status
        return True

    @property
    def provider_barrier_complete(self):
        return bool(self.provider_search_states) and all(
            state in TERMINAL_PROVIDER_STATES for state in self.provider_search_states.values()
        )

    def publish_search_results(self, generation, results):
        if generation != self.search_generation or not self.provider_barrier_complete:
            return False
        self.visible_provider_results = tuple(dict(row) for row in results or ())
        return True

    def change_mode(self, mode):
        if mode not in ('volume', 'chapter') or mode == self.mode:
            return False
        self.mode = mode
        self.search_generation += 1
        self.executed_query = ''
        self.provider_search_states = {}
        self.visible_provider_results = ()
        self.clear_selection()
        return True

    def clear_selection(self):
        self.selected_record_load_generation += 1
        self.selected_provider_record = None
        self.loaded_inventory = ()
        self.publication_manifest = None
        self.publication_projection = None
        self.chapter_acquisition_state = 'idle'
        self.chapter_structure_state = 'idle'
        self.pending_chapter_inventory = ()
        self.chapter_presentation_frozen = False
        self.volume_acquisition_state = 'idle'
        self.publication_resolution_state = 'idle'
        self.volume_inventory_final = False
        self.volume_native_count = 0
        self.volume_derived_count = 0
        self.volume_standalone_count = 0
        self.inventory_selection = frozenset()
        self.invalidate_downstream()

    def select_provider(self, record):
        identity = provider_identity(record)
        if identity is None:
            raise ValueError('A selected provider record requires source and immutable identity.')
        self.selected_record_load_generation += 1
        self.selected_provider_record = dict(record)
        self.loaded_inventory = ()
        self.publication_manifest = None
        self.publication_projection = None
        self.chapter_acquisition_state = 'idle'
        self.chapter_structure_state = 'pending'
        self.pending_chapter_inventory = ()
        self.chapter_presentation_frozen = False
        self.volume_acquisition_state = 'idle'
        self.publication_resolution_state = 'idle'
        self.volume_inventory_final = False
        self.volume_native_count = 0
        self.volume_derived_count = 0
        self.volume_standalone_count = 0
        self.inventory_selection = frozenset()
        self.invalidate_downstream()
        return self.selected_record_load_generation

    def begin_publication_resolution(self, selection_generation):
        if selection_generation != self.selected_record_load_generation:
            return False
        self.publication_resolution_state = 'pending'
        return True

    def settle_publication_resolution(self, selection_generation):
        if selection_generation != self.selected_record_load_generation:
            return False
        self.publication_resolution_state = 'terminal'
        return True

    def begin_volume_preparation(self, selection_generation, preparation_generation):
        if selection_generation != self.selected_record_load_generation:
            return False
        self.volume_preparation_generation = int(preparation_generation)
        self.volume_acquisition_state = 'pending'
        self.volume_inventory_final = False
        self.volume_native_count = 0
        self.volume_derived_count = 0
        self.volume_standalone_count = 0
        return True

    def settle_volume_acquisition(self, selection_generation, preparation_generation,
                                  native_count, standalone_count):
        if (selection_generation != self.selected_record_load_generation or
                preparation_generation != self.volume_preparation_generation):
            return False
        self.volume_acquisition_state = 'ready'
        self.volume_native_count = max(0, int(native_count or 0))
        self.volume_standalone_count = max(0, int(standalone_count or 0))
        return True

    def fail_volume_preparation(self, selection_generation, preparation_generation):
        if (selection_generation != self.selected_record_load_generation or
                preparation_generation != self.volume_preparation_generation):
            return False
        self.volume_acquisition_state = 'terminal_failure'
        self.volume_inventory_final = False
        return True

    def finalize_volume_inventory(self, selection_generation, preparation_generation,
                                  native_count, derived_count, standalone_count):
        if (selection_generation != self.selected_record_load_generation or
                preparation_generation != self.volume_preparation_generation):
            return False
        self.volume_acquisition_state = 'ready'
        self.volume_inventory_final = True
        self.volume_native_count = max(0, int(native_count or 0))
        self.volume_derived_count = max(0, int(derived_count or 0))
        self.volume_standalone_count = max(0, int(standalone_count or 0))
        return True

    @property
    def volume_presentation_state(self):
        if self.volume_acquisition_state == 'pending':
            return 'loading_acquisition'
        if self.volume_acquisition_state != 'ready':
            return 'idle'
        if self.volume_inventory_final:
            if (not self.volume_native_count and not self.volume_derived_count and
                    self.volume_standalone_count):
                return 'final_standalone'
            return 'ready'
        if self.volume_standalone_count:
            return ('resolving_publication' if self.publication_resolution_state != 'terminal'
                    else 'building_groups')
        return 'ready'

    def apply_inventory(self, generation, inventory):
        if generation != self.selected_record_load_generation:
            return False
        self.loaded_inventory = tuple(dict(row) for row in inventory or ())
        self.inventory_selection = frozenset()
        return True

    def apply_reference_inventory(self, generation, inventory):
        """Apply late metadata to the current inventory without clearing selection."""
        if generation != self.selected_record_load_generation:
            return False
        self.loaded_inventory = tuple(dict(row) for row in inventory or ())
        return True

    def apply_publication_manifest(self, generation, manifest):
        """Promote one normalized publication snapshot for the selected record."""
        if generation != self.selected_record_load_generation:
            return False
        self.publication_manifest = manifest
        return True

    def begin_chapter_preparation(self, selection_generation, preparation_generation):
        if selection_generation != self.selected_record_load_generation:
            return False
        self.chapter_preparation_generation = int(preparation_generation)
        self.chapter_acquisition_state = 'pending'
        self.pending_chapter_inventory = ()
        self.publication_projection = None
        self.chapter_presentation_frozen = False
        return True

    def settle_chapter_acquisition(self, selection_generation, preparation_generation,
                                   status, inventory=()):
        if (selection_generation != self.selected_record_load_generation or
                preparation_generation != self.chapter_preparation_generation or
                status not in TERMINAL_ACQUISITION_STATES or self.chapter_presentation_frozen):
            return False
        self.chapter_acquisition_state = status
        self.pending_chapter_inventory = tuple(dict(row) for row in inventory or ())
        return True

    def settle_publication_structure(self, selection_generation, status):
        if (selection_generation != self.selected_record_load_generation or
                status not in TERMINAL_STRUCTURE_STATES or self.chapter_presentation_frozen):
            return False
        self.chapter_structure_state = status
        return True

    @property
    def chapter_projection_ready(self):
        return (self.chapter_acquisition_state in TERMINAL_ACQUISITION_STATES and
                self.chapter_structure_state in TERMINAL_STRUCTURE_STATES and
                not self.chapter_presentation_frozen)

    def freeze_chapter_projection(self, selection_generation, preparation_generation,
                                  projection, inventory):
        if (selection_generation != self.selected_record_load_generation or
                preparation_generation != self.chapter_preparation_generation or
                not self.chapter_projection_ready):
            return False
        self.publication_projection = projection
        self.loaded_inventory = tuple(dict(row) for row in inventory or ())
        self.inventory_selection = frozenset()
        self.chapter_presentation_frozen = True
        return True

    def set_inventory_selection(self, identities):
        selection = frozenset(str(value) for value in identities or ())
        if selection == self.inventory_selection:
            return False
        self.inventory_selection = selection
        self.invalidate_downstream()
        return True

    def apply_source_configuration(self, enabled_sources):
        enabled = tuple(str(value) for value in enabled_sources or ())
        disabled = set(self.enabled_sources) - set(enabled)
        self.enabled_sources = enabled
        self.visible_provider_results = tuple(
            row for row in self.visible_provider_results
            if str(row.get('source_id') or '') not in disabled
        )
        if (self.selected_provider_record and
                str(self.selected_provider_record.get('source_id') or '') in disabled):
            self.clear_selection()

    def invalidate_downstream(self):
        """Invalidate downstream products without navigating or rebuilding them."""
        self.finalization_stale = True
        self.finalization_plan = ()
        if self.preview_state not in ('off', 'failed'):
            self.preview_state = 'stale'
            self.preview_stale = True

    def set_finalization_plan(self, plan):
        self.finalization_plan = tuple(plan or ())
        self.finalization_stale = False
        self.finalization_generation += 1

    def mark_preview_ready(self):
        self.preview_state = 'ready'
        self.preview_stale = False

    def mark_preview_failed(self):
        self.preview_state = 'failed'
        self.preview_stale = False

    def go_to(self, stage):
        if stage not in STAGES:
            raise ValueError(f'Unknown workflow stage: {stage}')
        self.stage = stage

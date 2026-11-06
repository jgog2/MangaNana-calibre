"""Deterministic terminal-state barrier for provider search display."""

from dataclasses import dataclass


TERMINAL_STATES = frozenset({'success','failure','cancelled','timeout'})


@dataclass(frozen=True)
class ProviderBarrierEntry:
    source_id: str
    state: str = 'pending'
    payload: object = None


class ProviderDisplayBarrier:
    def __init__(self, source_ids):
        self.source_ids=tuple(dict.fromkeys(str(value) for value in source_ids or ()))
        self._entries={source_id:ProviderBarrierEntry(source_id) for source_id in self.source_ids}

    def settle(self, source_id, state, payload=None):
        source_id=str(source_id)
        if source_id not in self._entries:
            return
        state=str(state)
        if state not in TERMINAL_STATES:
            raise ValueError(f'Non-terminal provider state: {state}')
        self._entries[source_id]=ProviderBarrierEntry(source_id,state,payload)

    @property
    def complete(self):
        return all(entry.state in TERMINAL_STATES for entry in self._entries.values())

    @property
    def settled_count(self):
        return sum(entry.state in TERMINAL_STATES for entry in self._entries.values())

    def is_terminal(self, source_id):
        entry=self._entries.get(str(source_id))
        return bool(entry and entry.state in TERMINAL_STATES)

    def ordered_successes(self):
        if not self.complete:
            return ()
        return tuple(
            self._entries[source_id].payload for source_id in self.source_ids
            if self._entries[source_id].state == 'success'
        )

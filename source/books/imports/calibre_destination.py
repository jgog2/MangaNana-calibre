"""A pinned destination identity, never an independently opened Calibre DB."""
from dataclasses import dataclass, asdict
import os
import weakref


class DestinationUnavailable(RuntimeError):
    import_status = 'conflicted'


@dataclass(frozen=True)
class LibraryIdentity:
    path: str
    library_id: str

    @classmethod
    def read(cls, db):
        path = os.path.normcase(os.path.realpath(os.fspath(db.library_path)))
        identifier = str(db.library_id or '')
        if not path or not identifier:
            raise DestinationUnavailable('Calibre did not provide a verifiable destination library identity.')
        return cls(path, identifier)


class DestinationDatabase:
    """Resolve/check every call so nested Qt prompts cannot retain a stale API."""
    def __init__(self, destination):
        self.destination = destination

    def __getattr__(self, name):
        if name == 'new_api':
            return self
        value = getattr(self.destination.api(), name)
        if not callable(value):
            return value
        def invoke(*args, **kwargs):
            return getattr(self.destination.api(), name)(*args, **kwargs)
        return invoke


class RejectedImporter:
    def __init__(self, reason):
        self.reason = reason

    def import_one(self, *_):
        return dict(status='conflicted', reason=self.reason)


class PinnedDestination:
    def __init__(self, gui):
        self._gui = weakref.ref(gui)
        self.identity = LibraryIdentity.read(gui.current_db)
        self.switching = False
        self.closed = False
        self.database = DestinationDatabase(self)
        self._verified = lambda:None
        self._verified_signature = None

    def api(self):
        gui = self._gui()
        if self.closed or gui is None or getattr(gui, 'shutting_down', False):
            raise DestinationUnavailable('The destination library is unavailable because Calibre is closing.')
        if self.switching:
            raise DestinationUnavailable('Calibre is switching libraries. Destination remains '+self.identity.path+'.')
        current = gui.current_db
        signature = (os.fspath(current.library_path), str(current.library_id or ''))
        verified = self._verified() is current and signature == self._verified_signature
        if not verified and LibraryIdentity.read(current) != self.identity:
            raise DestinationUnavailable('Destination remains '+self.identity.path+
                '. Return to that Calibre library before importing, or reopen MangaAnkā in the other library.')
        if not verified:
            try: self._verified = weakref.ref(current)
            except TypeError: self._verified = lambda:None
            self._verified_signature = signature
        return current.new_api

    def available(self):
        try:
            self.api()
            return True
        except DestinationUnavailable:
            return False

    def snapshot(self):
        return asdict(self.identity)

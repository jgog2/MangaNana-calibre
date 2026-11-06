"""Recover an exact existing Calibre output if format/metadata replacement fails.

Calibre's format and metadata APIs are separate writes. Keep a durable backup
before either write; retain it if the pinned destination cannot be restored.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class ReplacementFailure(RuntimeError):
    import_status = 'failed'
    def __init__(self, message, details):
        super().__init__(message)
        self.import_details = details


class ReplacementBackup:
    def __init__(self, db, bid, fmt, root=None):
        from calibre.constants import config_dir
        from calibre.ebooks.metadata.opf2 import metadata_to_opf
        self.db, self.bid, self.fmt = db, bid, fmt
        self.metadata = db.get_metadata(bid).deepcopy_metadata()
        self.cover = db.cover(bid)
        self.existed = db.has_format(bid, fmt)
        self.fields = {field: deepcopy(db.field_for(field, bid)) for field in (
            'title', 'authors', 'series', 'series_index', 'identifiers', 'tags',
            'languages', 'comments', 'publisher', 'rating', 'pubdate')}
        root = Path(root or Path(config_dir) / 'plugins' / 'MangaAnka-import-recovery')
        root.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix='replacement-', dir=root))
        self.format_path = self.path / ('previous.' + fmt.lower())
        try:
            if self.existed:
                db.copy_format_to(bid, fmt, str(self.format_path))
                self.digest = file_hash(self.format_path)
            (self.path / 'previous.opf').write_bytes(metadata_to_opf(self.metadata))
            if self.cover:
                (self.path / 'previous-cover.jpg').write_bytes(self.cover)
            self._record('prepared')
        except Exception:
            shutil.rmtree(self.path, ignore_errors=True)
            raise  # No database write has happened yet.

    def _record(self, status, **extra):
        document = dict(status=status, book_id=self.bid, format=self.fmt,
                        had_format=self.existed, identifiers=self.metadata.get_identifiers(), **extra)
        (self.path / 'recovery.json').write_text(json.dumps(document, indent=2), encoding='utf8')

    def discard(self):
        shutil.rmtree(self.path, ignore_errors=True)

    def restore(self, original_error):
        errors = []
        # Attempt both restorations independently. A failure in one must not
        # prevent recovering the other; every access still checks destination.
        actions = [lambda: self.db.add_format(self.bid, self.fmt, str(self.format_path), replace=True)
                   if self.existed else self.db.remove_formats({self.bid: (self.fmt,)}),
                   lambda: self.db.set_metadata(self.bid, self.metadata, ignore_errors=False, force_changes=True),
                   lambda: self.db.set_cover({self.bid: self.cover})]
        for action in actions:
            try:
                action()
            except Exception as exc:
                errors.append(str(exc))
        try:
            for field, expected in self.fields.items():
                if self.db.field_for(field, self.bid) != expected:
                    raise ValueError('Restored metadata differs: ' + field)
            if self.db.cover(self.bid) != self.cover:
                raise ValueError('Restored cover differs')
            if self.existed:
                check = self.path / 'restored-format-check'
                self.db.copy_format_to(self.bid, self.fmt, str(check))
                if file_hash(check) != self.digest:
                    raise ValueError('Restored format differs')
                check.unlink()
            elif self.db.has_format(self.bid, self.fmt):
                raise ValueError('New format remains after rollback')
        except Exception as exc:
            errors.append(str(exc))
        details = dict(book_id=self.bid, rollback_verified=not errors, partial_mutation=bool(errors))
        if errors:
            details.update(replacement_recovery_directory=str(self.path), rollback_errors=errors)
            try:
                self._record('restoration-incomplete', original_error=str(original_error), rollback_errors=errors)
            except OSError as exc:
                details['recovery_record_error'] = str(exc)
            message = 'Replacement failed; restoration could not be verified. Backup retained: ' + str(self.path)
        else:
            self.discard()
            message = 'Replacement failed; previous book and metadata restored.'
        raise ReplacementFailure(message + ' Cause: ' + str(original_error), details) from original_error

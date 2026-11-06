"""Acquisition-aware Calibre import and verifiable per-output accounting."""
from pathlib import Path
import json
import time
import hashlib
import re
from copy import deepcopy

IDENTIFIER = 'mangaanka_output'


def prepared_retry(requests, result, ledger):
    """Retry only uniquely owned, generated unresolved outputs; never successes.

    This is an explicit user action, not an automatic retry. The normal importer
    must revalidate destination, acquisition identity and duplicate policy again.
    Keep the original batch directory if it also contains other unresolved work.
    """
    wanted = {row['output_identity'] for row in ledger['outputs']
              if row['status'] in ('failed', 'conflicted', 'cancelled') and row.get('generated')}
    by_key = {}
    for item in result.get('files', ()):
        by_key.setdefault(item.get('output_identity'), []).append(item)
    eligible = {key for key in wanted if len(by_key.get(key, ())) == 1
                and Path(by_key[key][0]['path']).is_file()}
    selected = [deepcopy(row) for row in requests if row.get('output_identity') in eligible]
    if not selected:
        return None
    keys = {row['output_identity'] for row in selected}
    remaining = list(result.get('recovery_remaining') or ()) + [row for row in ledger['outputs']
        if row['status'] in ('failed', 'conflicted', 'cancelled') and row['output_identity'] not in keys]
    retry = dict(result, files=[deepcopy(by_key[row['output_identity']][0]) for row in selected],
                 failures=[], failed_volumes=[], failed_bonus=False,
                 recovery_remaining=deepcopy(remaining),
                 preserve_workdir=bool(result.get('preserve_workdir') or ledger.get('unexpected') or
                     remaining))
    return selected, retry


class OutputImporter:
    def __init__(self, db, recovery_root=None):
        self.db = db
        self.recovery_root = recovery_root
        self.refresh_owners()

    def refresh_owners(self):
        db=self.db
        self.owners = {}
        ids=db.all_book_ids()
        if hasattr(db,'all_field_for'):
            identifiers=db.all_field_for('identifiers',ids)
        else:
            identifiers={bid:db.field_for('identifiers',bid) for bid in ids}
        for bid, values in identifiers.items():
            key = (values or {}).get(IDENTIFIER)
            if key:
                self.owners.setdefault(key, []).append(bid)

    def verify(self, bid, mi, item, *, existing=False):
        db = self.db
        if bid not in db.all_book_ids():
            raise ValueError('Calibre returned a book ID absent from the library.')
        if (db.field_for('identifiers', bid) or {}).get(IDENTIFIER) != item['output_identity']:
            raise ValueError('Calibre output identity does not match the requested acquisition.')
        fmt = item.get('format', 'cbz').upper()
        if not db.has_format(bid, fmt):
            raise ValueError('Calibre book exists but its requested format is absent.')
        if not existing:
            from calibre.utils.localization import canonicalize_lang
            for field, expected in (('title', mi.title), ('series', mi.series), ('authors', tuple(mi.authors))):
                actual = db.field_for(field, bid)
                if field == 'authors': actual = tuple(actual or ())
                if actual != expected:
                    raise ValueError('Calibre stored different ' + field + ' metadata.')
            if float(db.field_for('series_index', bid)) != float(mi.series_index):
                raise ValueError('Calibre stored a different Series #.')
            if tuple(db.field_for('languages',bid) or ()) != tuple(canonicalize_lang(v) or v for v in mi.languages):
                raise ValueError('Calibre stored different language metadata.')
            info = db.format_metadata(bid, fmt, allow_cache=False)
            if info.get('size') != Path(item['path']).stat().st_size:
                raise ValueError('Calibre stored format size does not match the generated file.')
        return dict(book_id=bid, title=db.field_for('title', bid),
                    authors=list(db.field_for('authors',bid) or ()),languages=list(db.field_for('languages',bid) or ()),
                    series=db.field_for('series', bid), series_index=db.field_for('series_index', bid),
                    identifiers=dict(db.field_for('identifiers', bid) or {}),
                    format=fmt, format_size=db.format_metadata(bid, fmt, allow_cache=False).get('size'))

    def import_one(self, item, mi, policy='skip', ask=None):
        key = item.get('output_identity')
        payload=item.get('output_acquisition')
        expected='v2:'+hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',', ':'),ensure_ascii=False).encode('utf8')).hexdigest()
        if not payload or key != expected:
            raise ValueError('Generated output has no verifiable acquisition identity; import stopped.')
        mi.set_identifier(IDENTIFIER, key)
        owners = self.owners.get(key, [])
        if len(owners) > 1:
            return dict(status='conflicted', reason='Multiple library books already claim this output identity.', book_ids=owners)
        if owners:
            bid = owners[0]
            exists = self.db.has_format(bid, item.get('format', 'cbz').upper())
            if exists and policy == 'ask':
                before = self._record_signature(bid, item)
                policy = ask(item, bid) if ask else 'skip'
                # Non-modal Calibre can change/delete the book while this
                # decision runs its nested Qt loop. Never apply an old decision
                # to a different owner, changed book or reopened library handle.
                self.refresh_owners()
                if self.owners.get(key) != [bid] or self._record_signature(bid, item) != before:
                    return dict(status='conflicted', reason='The Calibre book changed during the duplicate decision. Prepared file retained for review.')
            if exists and policy != 'replace':
                return dict(status='skipped' if policy != 'cancel' else 'cancelled',
                            reason='Exact acquisition and requested format already exist; preserved existing book.',
                            verified=self.verify(bid, mi, item, existing=True))
            # Preserve unrelated identifiers and formats. Replacement is limited
            # to this exact output, never a matching title or numeric series index.
            identifiers = dict(self.db.field_for('identifiers', bid) or {})
            identifiers.update(mi.get_identifiers()); mi.set_identifiers(identifiers)
            from calibre_plugins.manganana.books.imports.replacement_backup import ReplacementBackup
            backup = ReplacementBackup(self.db, bid, item.get('format', 'cbz').upper(), self.recovery_root)
            try:
                added=self.db.add_format(bid, item.get('format', 'cbz').upper(), item['path'], replace=exists)
                if added is False:
                    raise ValueError('Calibre rejected the replacement format.')
                self.db.set_metadata(bid, mi, ignore_errors=False, force_changes=True)
                verified = self.verify(bid, mi, item)
            except Exception as exc:
                backup.restore(exc)
            backup.discard()
            return dict(status='updated', reason='Replaced exact output.' if exists else 'Added format to exact output.',
                        verified=verified)
        matches = set(self.db.find_identical_books(mi))
        # Calibre bibliographic duplicate detection intentionally ignores source
        # chapters. Only bypass it for positively distinguishable acquisitions.
        unknown = [bid for bid in matches if not re.fullmatch(r'v2:[0-9a-f]{64}',
                   (self.db.field_for('identifiers', bid) or {}).get(IDENTIFIER) or '')]
        if unknown:
            return dict(status='conflicted', book_ids=sorted(unknown),
                        reason='Matching bibliographic metadata belongs to an unidentified existing book. Prepared file retained for review.')
        ids, duplicates = self.db.add_books([(mi, {item.get('format', 'cbz').upper(): item['path']})],
                                           add_duplicates=bool(matches))
        if len(ids) != 1:
            return dict(status='conflicted', reason='Calibre did not create exactly one distinct requested book.',
                        duplicates=len(duplicates), book_ids=list(ids))
        bid = ids[0]
        self.owners.setdefault(key, []).append(bid)
        return dict(status='imported', verified=self.verify(bid, mi, item))

    def _record_signature(self, bid, item):
        if bid not in self.db.all_book_ids(): return None
        fields = {name:self.db.field_for(name, bid) for name in (
            'title','authors','series','series_index','identifiers','tags','languages',
            'comments','publisher','rating','pubdate','last_modified')}
        fields['format'] = dict(self.db.format_metadata(bid, item.get('format','cbz').upper(), allow_cache=False))
        fields['cover_modified'] = self.db.cover_last_modified(bid) if hasattr(self.db,'cover_last_modified') else None
        return deepcopy(fields)


class OutputReconciliation:
    """One authoritative reconciliation rule, synchronous or yielded by Qt."""
    def __init__(self, requests, files, importer, metadata, policy, ask=None, should_cancel=lambda:False, failures=()):
        self.requests=tuple(requests);self.outputs={};self.rows=[];self.position=0
        self.importer=importer;self.metadata=metadata;self.policy=policy;self.ask=ask
        self.should_cancel=should_cancel;self.failures=failures;self.cancel_requested=False
        for item in files:self.outputs.setdefault(item.get('output_identity'),[]).append(item)

    @property
    def done(self):return self.position==len(self.requests)

    def step(self):
        if self.done:return
        request=self.requests[self.position]
        key = request.get('output_identity')
        row = dict(output_identity=key, acquisition=request.get('output_acquisition'),
                   title=request.get('title'), selected=True, planned=True, generated=False,
                   import_attempted=False, status='failed')
        candidates = self.outputs.pop(key, [])
        if len(candidates) != 1:
            row['reason'] = 'No generated file for requested output.' if not candidates else 'Multiple files claim one output identity.'
            failure=next((v for v in self.failures if v.get('output_identity')==key),None)
            if failure:row['reason']=failure.get('error') or row['reason']
        else:
            item = candidates[0]
            try:size=Path(item['path']).stat().st_size
            except OSError:size=0
            row.update(generated=True, generated_file=item['path'], format=item.get('format'),
                       bytes=size,
                       effective_metadata={f:item.get(f) for f in ('title','author','series','series_index','chapter_number')})
            if self.cancel_requested or self.should_cancel():
                row.update(status='cancelled', reason='Import cancelled before this output was attempted.')
            else:
                try:
                    row['import_attempted'] = True
                    outcome = self.importer.import_one(item, self.metadata(item), self.policy, self.ask)
                    row.update(outcome)
                    if outcome['status']=='cancelled':self.cancel_requested=True
                except Exception as exc:
                    row.update(status=getattr(exc,'import_status','failed'), reason=str(exc))
                    row.update(getattr(exc, 'import_details', {}))
        self.rows.append(row);self.position+=1
        return row

    def result(self):
        if not self.done:raise RuntimeError('Import accounting is incomplete.')
        unexpected=[dict(output_identity=key,files=[i['path'] for i in items],reason='Unrequested generated output; not imported.')
                    for key,items in self.outputs.items()]
        return dict(version=1,timestamp=time.time(),requested=len(self.requests),outputs=self.rows,unexpected=unexpected,
                    counts={status:sum(r['status']==status for r in self.rows) for status in
                            ('imported','updated','skipped','conflicted','failed','cancelled')})


def reconcile_outputs(requests, files, importer, metadata, policy, ask=None, should_cancel=lambda:False, failures=()):
    """Exactly one terminal ledger row per request, including partial failures."""
    run=OutputReconciliation(requests,files,importer,metadata,policy,ask,should_cancel,failures)
    while not run.done:run.step()
    return run.result()


def save_ledger(ledger, directory):
    """Keep bounded recent accounting independent of disposable prepared files."""
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    path = directory / ('MangaAnka-output-' + str(time.time_ns()) + '.json')
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf8')
    for old in sorted(directory.glob('MangaAnka-output-*.json'))[:-10]:
        old.unlink()
    return str(path)

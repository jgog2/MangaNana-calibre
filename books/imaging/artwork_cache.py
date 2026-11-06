"""Bounded public-artwork resources; publication qualification stays in manifests.

No QWidget/QPixmap ownership, acquisition pages, cookies or credentials belong
here. Disk access and decoding are worker-only; peek operations are memory-only.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Condition, Event, RLock, Thread
from urllib.parse import urlsplit, urlunsplit, parse_qsl
from collections import Counter, OrderedDict
import sqlite3
import time
import weakref

from calibre_plugins.manganana.common.bounded_cache import BoundedCache

CONTRACT='publication-artwork-resource-v1'
MEMORY_BYTES=32*1024*1024
DECODED_BYTES=16*1024*1024
DISK_BYTES=96*1024*1024
DISK_FILE_BYTES=128*1024*1024
TTL=3600
NEGATIVE_TTL=60

class ResourceFailure(Exception):pass

def resource_identity(candidate):
    """Exact resource + transport authority; never normalize away URL queries."""
    try:parts=urlsplit(candidate.url)
    except ValueError:return sha256((CONTRACT+'|invalid|'+candidate.source+'|'+candidate.url).encode()).hexdigest(),False
    host=(parts.hostname or '').lower()
    neutral=(candidate.source in ('mangadex','mangadex_artwork')and host=='uploads.mangadex.org' or
             candidate.source=='bookwalker'and(host=='bookwalker.jp'or host.endswith('.bookwalker.jp'))or
             candidate.source=='google_books'and(host in ('books.google.com','books.google.co.jp')or host.endswith('.googleusercontent.com')))
    authority=candidate.source if not neutral else 'public:'+('mangadex-artwork'if candidate.source in ('mangadex','mangadex_artwork')else candidate.source)
    netloc=parts.netloc if parts.username or parts.password else parts.netloc.lower()
    normalized=urlunsplit((parts.scheme.lower(),netloc,parts.path,parts.query,''))
    key=sha256((CONTRACT+'|'+authority+'|'+normalized).encode()).hexdigest()
    allowed={'id','printsec','img','zoom','edge','source','jscmd','vid','hl','w','h','fife'}
    public=bool(neutral and candidate.publication_key and parts.scheme=='https'and not parts.username and not parts.password
                and all(k in allowed for k,_ in parse_qsl(parts.query,keep_blank_values=True)))
    return key,public

@dataclass(frozen=True)
class Resource:
    key:str
    raw:bytes
    preview:bytes
    digest:str
    created:float

class Flight:
    def __init__(self):
        self.event=Event();self.subscribers={};self.result=None;self.error=None

class ArtworkResources:
    def __init__(self,path=None,clock=None,memory_bytes=MEMORY_BYTES,disk_bytes=DISK_BYTES):
        self.path=Path(path)if path else None;self.clock=clock or time.time
        self.memory=BoundedCache(memory_bytes,256,lambda r:len(r.raw)+len(r.preview))
        self.decoded=BoundedCache(DECODED_BYTES,128,lambda im:im.sizeInBytes())
        self.negative=BoundedCache(64*1024,256,lambda r:128)
        self.associations=BoundedCache(128*1024,512,lambda r:256)
        self.lock=RLock();self.condition=Condition(self.lock);self.flights={};self.disk_bytes=disk_bytes
        self.stats=Counter();self.disk_disabled=False
        self.pending_writes=OrderedDict();self.pending_bytes=0;self.writing_bytes=0;self.writer=None
        self.disk_keys=None

    @staticmethod
    def _drain_writes(cache):
        # Finite worker: releases its cache reference once the queue is empty.
        # No Qt objects, GUI callbacks or network operations are involved.
        try:
            while True:
                with cache.lock:
                    if not cache.pending_writes:break
                    _,(value,candidate)=cache.pending_writes.popitem(last=False)
                    cache.writing_bytes=len(value.raw)+len(value.preview)
                    cache.pending_bytes-=cache.writing_bytes
                cache._write(value,candidate)
        except Exception:
            with cache.lock:
                cache.disk_disabled=True;cache.stats['writer_unavailable']+=1
                cache.pending_writes.clear();cache.pending_bytes=0
        finally:
            with cache.lock:
                cache.writing_bytes=0;cache.writer=None
                if cache.pending_writes:cache._start_writer()

    def _start_writer(self):
        self.writer=Thread(target=self._drain_writes,args=(self,),name='MangaAnka artwork cache',daemon=True)
        self.writer.start()

    def _persist(self,value,candidate):
        cost=len(value.raw)+len(value.preview)
        if cost>16*1024*1024 or self.disk_disabled:return
        with self.lock:
            old=self.pending_writes.pop(value.key,None)
            if old:self.pending_bytes-=len(old[0].raw)+len(old[0].preview)
            self.pending_writes[value.key]=(value,candidate);self.pending_bytes+=cost
            while self.pending_writes and(self.pending_bytes+self.writing_bytes>16*1024*1024 or len(self.pending_writes)>32):
                _,(expired,_)=self.pending_writes.popitem(last=False)
                self.pending_bytes-=len(expired.raw)+len(expired.preview)
            if self.writer is None:
                self._start_writer()

    def peek(self,key):
        with self.lock:
            self.stats['memory_lookups']+=1
            value=self.memory.get(key)
            if value and 0<=self.clock()-value.created<TTL:
                self.stats['memory_peek_hits']+=1;return value
            if value:self.memory.pop(key,None)
        return None

    def rejected(self,key):
        with self.lock:
            value=self.negative.get(key)
            if value and 0<=self.clock()-value[0]<NEGATIVE_TTL:return value[1]
            self.negative.pop(key,None)
        return ''

    def retry(self,key):
        with self.lock:self.negative.pop(key,None)

    def reject(self,key,reason):
        with self.lock:
            value=self.memory.pop(key,None)
            if value:self.decoded.pop(value.digest,None)
            self.negative[key]=(self.clock(),reason)
            if self.disk_keys is not None:self.disk_keys.discard(key)
            self.stats['display_rejected']+=1

    def associate(self,candidate,value):
        key,persist=resource_identity(candidate)
        if not candidate.publication_key:return
        with self.lock:
            if self.associations.get(candidate.publication_key)==key:return
            self.associations[candidate.publication_key]=key
        if persist:self._persist(value,candidate)

    def _db(self):
        if not self.path or self.disk_disabled:return None
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            if self.path.exists()and self.path.stat().st_size>DISK_FILE_BYTES:raise ValueError('oversized cache')
            db=sqlite3.connect(str(self.path),timeout=.25)
            db.execute('PRAGMA auto_vacuum=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS resources (key TEXT PRIMARY KEY, raw BLOB, preview BLOB, digest TEXT, preview_digest TEXT, created REAL, accessed REAL, cost INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS associations (key TEXT PRIMARY KEY, resource TEXT, source TEXT, identity TEXT, accessed REAL)')
            return db
        except (OSError,ValueError,sqlite3.Error):
            if 'db'in locals():db.close()
            self.disk_disabled=True;self.stats['disk_unavailable']+=1
            return None

    def _read(self,key):
        # Load a bounded key index once, in a worker. A cold resource absent
        # from disk must not wait behind writes for unrelated visible covers.
        if self.disk_keys is None:
            db=self._db()
            if db is None:self.disk_keys=set();return None
            try:
                self.disk_keys={r[0]for r in db.execute('SELECT key FROM resources WHERE created>? ORDER BY accessed DESC LIMIT 256',(self.clock()-TTL,))}
            except sqlite3.Error:self.disk_keys=set()
            finally:db.close()
        if key not in self.disk_keys:return None
        db=self._db()
        if db is None:return None
        try:
            with db:
                row=db.execute('SELECT raw,preview,digest,preview_digest,created FROM resources WHERE key=?',(key,)).fetchone()
                if not row:return None
                raw,preview,digest,pdigest,created=row
                if len(raw)>24*1024*1024 or len(preview)>2*1024*1024 or self.clock()-created<0 or self.clock()-created>=TTL or sha256(raw).hexdigest()!=digest or sha256(preview).hexdigest()!=pdigest:
                    db.execute('DELETE FROM resources WHERE key=?',(key,));self.stats['disk_rejected']+=1;return None
                db.execute('UPDATE resources SET accessed=? WHERE key=?',(self.clock(),key))
                self.stats['disk_hit']+=1
                return Resource(key,raw,preview,digest,created)
        except (sqlite3.Error,TypeError,ValueError):
            self.stats['disk_unavailable']+=1;return None
        finally:db.close()

    def _write(self,value,candidate):
        cost=len(value.raw)+len(value.preview)
        if cost>self.disk_bytes:return
        db=self._db()
        if db is None:return
        try:
            with db:
                now=self.clock()
                db.execute('INSERT OR REPLACE INTO resources VALUES(?,?,?,?,?,?,?,?)',
                    (value.key,value.raw,value.preview,value.digest,sha256(value.preview).hexdigest(),value.created,now,cost))
                db.execute('INSERT OR REPLACE INTO associations VALUES(?,?,?,?,?)',
                    (candidate.publication_key,value.key,candidate.source,sha256(candidate.source_identity.encode()).hexdigest(),now))
                while True:
                    count,total=db.execute('SELECT COUNT(*),COALESCE(SUM(cost),0) FROM resources').fetchone()
                    if count<=256 and total<=self.disk_bytes:break
                    db.execute('DELETE FROM resources WHERE key=(SELECT key FROM resources ORDER BY accessed LIMIT 1)')
                    self.stats['disk_evicted']+=1
                db.execute('DELETE FROM associations WHERE resource NOT IN (SELECT key FROM resources)')
                db.execute('DELETE FROM associations WHERE key NOT IN (SELECT key FROM associations ORDER BY accessed DESC LIMIT 512)')
                self.stats['disk_retained_bytes']=total
                self.disk_keys={r[0]for r in db.execute('SELECT key FROM resources')}
        except sqlite3.Error:self.stats['disk_unavailable']+=1
        finally:db.close()

    def acquire(self,candidate,fetch,prepare,cancelled):
        key,persist=resource_identity(candidate);token=object();check=cancelled or(lambda:False)
        if check():raise InterruptedError()
        with self.condition:
            value=self.peek(key)
            if value:self.stats['memory_hit']+=1;return value
            reason=self.rejected(key)
            if reason:raise ResourceFailure(reason)
            while key not in self.flights and len(self.flights)>=4:
                if check():raise InterruptedError()
                self.condition.wait(.05)
            leader=key not in self.flights
            flight=self.flights.setdefault(key,Flight());flight.subscribers[token]=check
            self.stats['leaders'if leader else'joined']+=1
        try:
            if leader:
                try:
                    value=self._read(key)if persist else None
                    from_disk=value is not None
                    if value is None:
                        start=time.perf_counter();raw=fetch();self.stats['fetch_ms']+=(time.perf_counter()-start)*1000;self.stats['fetches']+=1
                        start=time.perf_counter();reason,preview=prepare(raw);self.stats['prepare_ms']+=(time.perf_counter()-start)*1000
                        if reason:raise ResourceFailure(reason)
                        value=Resource(key,raw,preview,sha256(raw).hexdigest(),self.clock())
                    with self.lock:
                        active=any(not stop()for stop in flight.subscribers.values())
                        if active:
                            self.memory[key]=value;self.associations[candidate.publication_key or key]=key
                    if active and persist and not from_disk:self._persist(value,candidate)
                    flight.result=value
                except Exception as exc:
                    flight.error=exc if isinstance(exc,ResourceFailure)else ResourceFailure('fetch failed')
                    with self.lock:
                        if any(not stop()for stop in flight.subscribers.values()):self.negative[key]=(self.clock(),str(flight.error))
                finally:
                    with self.condition:
                        self.flights.pop(key,None);flight.event.set();self.condition.notify_all()
            else:
                while not flight.event.wait(.025):
                    if check():raise InterruptedError()
            if check():raise InterruptedError()
            if flight.error:raise flight.error
            return flight.result
        finally:
            with self.lock:flight.subscribers.pop(token,None)

    def image(self,value):
        """Called in image workers. QImage is implicitly shared; no QPixmap here."""
        from qt.core import QImage
        with self.lock:
            image=self.decoded.get(value.digest)
            if image is None:
                start=time.perf_counter();image=QImage.fromData(value.preview)
                if image.isNull():raise ResourceFailure('invalid display image')
                self.decoded[value.digest]=image;self.stats['image_decodes']+=1;self.stats['image_decode_ms']+=(time.perf_counter()-start)*1000
            return QImage(image)

    def peek_image(self,value):
        with self.lock:return self.decoded.get(value.digest)

    def snapshot(self):
        with self.lock:return dict(self.stats,memory_bytes=self.memory.bytes_used,decoded_bytes=self.decoded.bytes_used,
            resources=len(self.memory),associations=len(self.associations),in_flight=len(self.flights),disk_disabled=self.disk_disabled,
            pending_write_bytes=self.pending_bytes,writing_bytes=self.writing_bytes,pending_writes=len(self.pending_writes),writer_active=self.writer is not None)

_caches=weakref.WeakValueDictionary()
_cache_lock=RLock()
def publication_artwork_cache(config_directory):
    path=Path(config_directory)/'plugins/MangaNana-publication-artwork.sqlite3'
    key=str(path.resolve())
    with _cache_lock:
        cache=_caches.get(key)
        if cache is None:cache=ArtworkResources(path);_caches[key]=cache
        return cache

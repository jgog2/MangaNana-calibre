"""Bounded loopback HTTP faults; never contacts real providers.

calibre-debug -e tools/transport_faults.py -- --plugin <ZIP> --out <new.json>
"""
import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time


def main(args):
    if args.out.exists(): raise ValueError('Preserve existing evidence; choose a new output')
    from calibre.customize.zipplugin import loader
    loader.load(str(args.plugin.resolve()))
    from calibre_plugins.manganana.providers.transport import read_response, ResponseLimitExceeded
    from calibre_plugins.manganana.providers.mangadex_source import MangaDexSource
    from calibre_plugins.manganana.providers.mangapill_source import MangaPillSource
    from calibre_plugins.manganana.providers.weebcentral_source import WeebCentralSource
    from calibre_plugins.manganana.providers.mangak_source import MangaKSource
    from calibre_plugins.manganana.providers.atsu_source import AtsuSource
    calls=Counter();rows=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*a): pass
        def do_GET(self):
            calls[self.path]+=1
            try:
                if self.path=='/rate':
                    self.send_response(429);self.send_header('Retry-After','60');self.send_header('Content-Length','0');self.end_headers();return
                if self.path=='/retry' and calls[self.path]<3:
                    self.send_response(503);self.send_header('Content-Length','0');self.end_headers();return
                self.send_response(200)
                if self.path=='/oversized':
                    self.send_header('Content-Length',str(65*1024*1024));self.end_headers();return
                if self.path=='/trickle':
                    self.send_header('Content-Length',str(1024*1024));self.end_headers()
                    for _ in range(1024):self.wfile.write(b'x'*1024);self.wfile.flush();time.sleep(.02)
                    return
                if self.path=='/chunked':
                    self.send_header('Transfer-Encoding','chunked');self.end_headers()
                    for _ in range(3):self.wfile.write(b'10000\r\n'+b'x'*65536+b'\r\n');self.wfile.flush()
                    self.wfile.write(b'0\r\n\r\n');return
                body=b'valid-marker-response'*5000
                self.send_header('Content-Length',str(1000000 if self.path=='/truncated' else len(body)))
                self.send_header('Content-Type','application/octet-stream');self.end_headers()
                self.wfile.write(body)
                if self.path=='/truncated':self.close_connection=True
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_address[1])
    def check(value,name,**details):
        rows.append(dict(name=name,passed=bool(value),**details))
        if not value: raise RuntimeError(name)
    try:
        import urllib.request
        with urllib.request.urlopen(base+'/ok',timeout=2) as response:
            result=read_response(response,200000)
        check(result==b'valid-marker-response'*5000,'Actual HTTP bytes preserved',bytes=len(result))
        for path,limit,kind in (('/oversized',64*1024*1024,ResponseLimitExceeded),('/chunked',100000,ResponseLimitExceeded),('/truncated',2000000,OSError)):
            try:
                with urllib.request.urlopen(base+path,timeout=2) as response:read_response(response,limit)
            except kind as exc:check(True,'Explicit HTTP fault '+path,error=type(exc).__name__,message=str(exc))
            else:check(False,'Explicit HTTP fault '+path)
        for cls in (MangaDexSource,MangaPillSource,WeebCentralSource,MangaKSource,AtsuSource):
            start=time.monotonic();before=calls['/trickle']
            def cancel():
                if time.monotonic()-start>.15: raise InterruptedError('Controlled close')
            try: cls().with_cancel_check(cancel).fetch_binary(base+'/trickle')
            except InterruptedError:
                elapsed=time.monotonic()-start
                check(elapsed<1 and calls['/trickle']==before+1,'Actual streaming cancellation '+cls.source_id,elapsed_s=elapsed,requests=calls['/trickle']-before)
            else:check(False,'Actual streaming cancellation '+cls.source_id)
        start=time.monotonic()
        def rate_cancel():
            if time.monotonic()-start>.15: raise InterruptedError('Controlled close while waiting')
        try:MangaDexSource().with_cancel_check(rate_cancel)._api_json(base+'/rate')
        except InterruptedError:check(calls['/rate']==1,'Retry-After wait cancelled without retry',elapsed_s=time.monotonic()-start)
        else:check(False,'Retry-After wait cancelled without retry')
        start=time.monotonic();result=MangaPillSource().fetch_binary(base+'/retry')
        check(calls['/retry']==3 and result==b'valid-marker-response'*5000,'Transient retries retain pacing and successful bytes',requests=calls['/retry'],elapsed_s=time.monotonic()-start)
    finally:
        server.shutdown();server.server_close();thread.join(2)
        import hashlib
        document=dict(plugin=str(args.plugin.resolve()),sha256=hashlib.sha256(args.plugin.read_bytes()).hexdigest(),checks=rows,requests=dict(calls),network_scope='127.0.0.1 only; no provider traffic',server_thread_stopped=not thread.is_alive())
        document['passed']=bool(rows) and all(r['passed'] for r in rows) and document['server_thread_stopped']
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(document,indent=2),encoding='utf8')
    print(json.dumps(dict(passed=document['passed'],checks=len(rows),out=str(args.out))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plugin',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    argv=sys.argv[1:]
    if argv and argv[0]=='--':argv=argv[1:]
    main(parser.parse_args(argv))

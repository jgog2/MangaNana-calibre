"""Offline process-interruption probes in a newly created disposable directory.

Run with calibre-debug -e tools/persistence_faults.py -- --root <new-directory>
--plugin <test-plugin.zip>. No installed profile/library is used or modified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load_plugin(archive):
    if archive:
        from calibre.customize.zipplugin import loader
        loader.load(str(archive))
    else:
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from tools.source_bootstrap import ensure_source_package
        ensure_source_package()


def listing(identity):
    return dict(source_id='mangapill', id=identity, title='Controlled '+identity,
                url='https://mangapill.com/manga/'+identity)


def child(args):
    load_plugin(args.plugin)
    if args.child=='favorites':
        from calibre_plugins.manganana.discovery.saved_manga import FavoritesStore
        store=FavoritesStore(args.root/'bookmarks')
        def terminate_after_fsync(source,target):
            (args.root/'favorites-interrupted.json').write_text(json.dumps(dict(
                recovery=str(source),target=str(target))),encoding='utf8')
            os._exit(73)
        os.replace=terminate_after_fsync
        store.toggle(listing('2'));store.close(10)
        raise RuntimeError('Interruption gate not reached')
    from calibre.db.legacy import LibraryDatabase
    from calibre.ebooks.metadata.book.base import Metadata
    from calibre_plugins.manganana.books.imports.output_import import OutputImporter
    database=LibraryDatabase(str(args.library));db=database.new_api
    item=json.loads((args.root/'replacement-item.json').read_text(encoding='utf8'))
    class CrashAfterFormat:
        def __getattr__(self,name): return getattr(db,name)
        def add_format(self,*a,**kw):
            db.add_format(*a,**kw)
            os._exit(74)
    mi=Metadata('After interruption',['Controlled author']);mi.series='Fixture';mi.series_index=9.;mi.languages=['eng']
    OutputImporter(CrashAfterFormat(),recovery_root=args.root/'replacement-backups').import_one(item,mi,'replace')
    raise RuntimeError('Replacement interruption gate not reached')


def main(args):
    require(os.name!='nt' or len(str(args.library))<89,'Choose a shorter disposable library path: Calibre limits Windows library paths to 88 characters')
    require(not args.library.exists(),'Disposable library must be new')
    require(not args.root.exists(),'Evidence destination must be new')
    args.root.mkdir(parents=True)
    load_plugin(args.plugin)
    report=dict(plugin=str(args.plugin),plugin_sha256=hashlib.sha256(args.plugin.read_bytes()).hexdigest() if args.plugin else None,checks=[])
    def check(value,message):
        report['checks'].append(dict(name=message,passed=bool(value)))
        (args.root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        require(value,message)
    def run(mode,expected):
        env=os.environ.copy();env['CALIBRE_CONFIG_DIRECTORY']=str(args.root/('child-profile-'+mode))
        command=[sys.executable,'-e',str(Path(__file__).resolve()),'--','--root',str(args.root),'--child',mode]
        if args.plugin: command+=['--plugin',str(args.plugin)]
        command+=['--library',str(args.library)]
        result=subprocess.run(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
        (args.root/(mode+'.console.log')).write_bytes(result.stdout)
        report.setdefault('processes',[]).append(dict(mode=mode,exit_code=result.returncode))
        check(result.returncode==expected,'Exact forced interruption exit '+mode)
    from calibre_plugins.manganana.discovery.saved_manga import FavoritesStore
    first=FavoritesStore(args.root/'bookmarks');first.toggle(listing('1'))
    check(first.close(),'Initial Favorites commit')
    previous=first.path.read_bytes();run('favorites',73)
    interrupted=json.loads((args.root/'favorites-interrupted.json').read_text())
    recovery=Path(interrupted['recovery'])
    check(first.path.read_bytes()==previous,'Forced exit preserves committed Favorites byte-for-byte')
    check({r['listing']['id'] for r in json.loads(recovery.read_bytes())['records']}=={'1','2'},'Fsynced pending Favorites conserve both edits')
    reopened=FavoritesStore(args.root/'bookmarks')
    check('interrupted' in reopened.warning and str(recovery.parent) in reopened.warning,'Restart surfaces recovery warning')
    check({r['id'] for r in reopened.records.values()}=={'1'},'No arbitrary application of uncommitted edit')
    reopened.close()
    from calibre.db.legacy import LibraryDatabase
    from calibre.ebooks.metadata.book.base import Metadata
    database=LibraryDatabase(str(args.library));db=database.new_api
    old=args.root/'before.cbz';new=args.root/'after.cbz'
    for path,marker in ((old,'before'),(new,'after')):
        from io import BytesIO
        from PIL import Image
        stream=BytesIO();Image.new('RGB',(32,48),'#66b7a8' if marker=='before' else '#ed1e45').save(stream,'PNG')
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('001.png',stream.getvalue());z.writestr('controlled-marker.txt',marker)
    payload=dict(kind='chapter',source_id='fixture',series_ref='isolated',chapter_ids=['opaque'])
    key='v2:'+hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    mi=Metadata('Before interruption',['Controlled author']);mi.series='Fixture';mi.series_index=2.;mi.languages=['eng'];mi.set_identifier('mangaanka_output',key)
    ids,_=db.add_books([(mi,{'CBZ':str(old)})]);bid=ids[0]
    item=dict(output_identity=key,output_acquisition=payload,path=str(new),format='cbz')
    (args.root/'replacement-item.json').write_text(json.dumps(item),encoding='utf8')
    database.close();run('replacement',74)
    database=LibraryDatabase(str(args.library));db=database.new_api
    check(db.field_for('title',bid)=='Before interruption','Forced exit exposes separate metadata/format transaction boundary')
    current=args.root/'interrupted.cbz';db.copy_format_to(bid,'CBZ',str(current))
    check(current.read_bytes()==new.read_bytes(),'New format was committed before forced exit')
    backups=list((args.root/'replacement-backups').glob('replacement-*'))
    check(len(backups)==1,'One durable replacement backup retained')
    backup=backups[0]
    check((backup/'previous.cbz').read_bytes()==old.read_bytes(),'Original format retained byte-for-byte')
    check((backup/'previous.opf').is_file() and json.loads((backup/'recovery.json').read_text())['book_id']==bid,'Original metadata and exact record recovery evidence retained')
    # Demonstrate deliberate recovery in this test library only, after validating
    # its exact output identifier. This is not an automatic startup migration.
    check(db.field_for('identifiers',bid)['mangaanka_output']==key,'Recovery checks exact acquisition owner')
    from calibre.ebooks.metadata.opf2 import OPF
    with (backup/'previous.opf').open('rb') as stream: restored=OPF(stream,basedir=str(backup)).to_book_metadata()
    db.add_format(bid,'CBZ',str(backup/'previous.cbz'),replace=True)
    db.set_metadata(bid,restored,ignore_errors=False,force_changes=True)
    destination=args.root/'recovered.cbz';db.copy_format_to(bid,'CBZ',str(destination))
    check(destination.read_bytes()==old.read_bytes() and db.field_for('title',bid)=='Before interruption' and db.field_for('series_index',bid)==2.,'Controlled recovery restores real Calibre format/title/index')
    database.close();report['passed']=True
    (args.root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(dict(passed=True,checks=len(report['checks']),report=str(args.root/'report.json'))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--plugin',type=Path)
    parser.add_argument('--child',choices=('favorites','replacement'))
    parser.add_argument('--library',type=Path,help='New disposable Calibre library; defaults to ROOT/library')
    argv=sys.argv[1:]
    if argv and argv[0]=='--':argv=argv[1:]
    args=parser.parse_args(argv);args.root=args.root.resolve()
    args.library=(args.library or args.root/'library').resolve()
    if args.plugin:args.plugin=args.plugin.resolve()
    if args.child: child(args)
    else: main(args)

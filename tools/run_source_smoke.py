"""Install only into fresh disposable paths and launch the actual Calibre action."""
import argparse,json,os,subprocess,sys,uuid,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibre-directory',required=True);parser.add_argument('--plugin',required=True)
    parser.add_argument('--sandbox-root',default=str(ROOT/'build/source-smoke'))
    parser.add_argument('--library-root',default='')
    args=parser.parse_args();token='source-'+uuid.uuid4().hex[:12]
    base=Path(args.sandbox_root).resolve()/token
    library=(Path(args.library_root).resolve() if args.library_root else Path(tempfile.gettempdir())/'MangaAnka-source-libraries')/token
    assert not base.exists() and not library.exists()
    if sys.platform=='win32' and len(str(library))>=89:
        raise RuntimeError('Calibre requires a library path shorter than 89 characters here. Choose a shorter --library-root; no installation performed.')
    if sys.platform=='win32':
        check=subprocess.run(['powershell','-NoProfile','-Command',"Get-Process -Name calibre -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],capture_output=True,text=True)
        if check.stdout.strip():raise RuntimeError('Close ordinary Calibre before starting the isolated smoke')
    base.mkdir(parents=True);library.mkdir(parents=True)
    profile=base/'config';plugin=Path(args.plugin).resolve();assert plugin.is_file()
    env=os.environ.copy();env.update(CALIBRE_CONFIG_DIRECTORY=str(profile),SOURCE_SMOKE_OUT=str(base),SOURCE_SMOKE_LIBRARY=str(library),SOURCE_SMOKE_PLUGIN=str(plugin))
    for k in ('MANGAANKA_CATALOG_ENABLED','MANGAANKA_CATALOG_PATH','MANGAANKA_PUBLICATION_BRIDGE_PATH','MANGAANKA_MANGAK_CONTINUATIONS_ENABLED'):env.pop(k,None)
    exe=lambda name:str(Path(args.calibre_directory)/(name+('.exe' if sys.platform=='win32' else '')))
    with (base/'native.console.log').open('w',encoding='utf8') as log:
        install=subprocess.run([exe('calibre-customize'),'-a',str(plugin)],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=90)
        assert install.returncode==0
        try:
            process=subprocess.run([exe('calibre-debug'),'-e',str(ROOT/'tools/run_qt_checks.py'),'--',str(ROOT/'tools/source_calibre_smoke.py')],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=120)
            exit_code=process.returncode;timed_out=False
        except subprocess.TimeoutExpired:
            exit_code=None;timed_out=True
    result_path=base/'native-results.json'
    record=json.loads(result_path.read_text(encoding='utf8')) if result_path.exists() else dict(passed=False,errors=['Native startup did not produce a report; inspect native.console.log'],profile=str(profile),library=str(library))
    record['exit_code']=exit_code;record['timed_out']=timed_out
    console=(base/'native.console.log').read_text(encoding='utf8')
    record['passed']=record['passed'] and exit_code==0 and not timed_out and 'Traceback (most recent call last)' not in console
    (base/'native-results.json').write_text(json.dumps(record,indent=2),encoding='utf8');print(str(base/'native-results.json'))
    return 0 if record['passed'] else 1
if __name__=='__main__':raise SystemExit(main())

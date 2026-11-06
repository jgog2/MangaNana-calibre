"""Portable, offline module-isolated runner; never loads a normal Calibre profile."""
import argparse,json,os,subprocess,sys,time,uuid,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibre-debug',default='calibre-debug')
    parser.add_argument('--modules',default='')
    parser.add_argument('--data-root',default=str(Path(tempfile.gettempdir())/'MangaAnka-source-tests'))
    args=parser.parse_args()
    out=ROOT.parent/'builds/source-tests'/uuid.uuid4().hex;out.mkdir(parents=True)
    data=Path(args.data_root).resolve()/out.name;assert not data.exists();data.mkdir(parents=True)
    policy=json.loads((ROOT/'tests/source_suite_policy.json').read_text(encoding='utf8'))
    available=sorted(p.stem for p in (ROOT/'tests').glob('test_*.py'))
    modules=args.modules.split(',') if args.modules else available
    assert all(m in available for m in modules),'Unknown test module'
    rows=[];start=time.monotonic()
    for module in modules:
        if module in policy['unavailable_modules']:
            rows.append(dict(module=module,unavailable=policy['unavailable_modules'][module]));continue
        temporary=data/'temp'/module;temporary.mkdir(parents=True)
        env=os.environ.copy();env.update(CALIBRE_CONFIG_DIRECTORY=str(data/'profiles'/module),SOURCE_TEST_OUT=str(out),
            TEMP=str(temporary),TMP=str(temporary),CALIBRE_TEMP_DIR=str(temporary))
        with (out/(module+'.console.log')).open('w',encoding='utf8') as log:
            try:
                process=subprocess.run([args.calibre_debug,'-e',str(ROOT/'tools/source_test_module.py'),'--',module],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
                row=dict(module=module,exit_code=process.returncode)
            except subprocess.TimeoutExpired:row=dict(module=module,timeout=True)
        record=out/(module+'.json')
        if record.exists():row.update(json.loads(record.read_text(encoding='utf8')))
        rows.append(row);print(module,row.get('run'),row.get('failures'),row.get('errors'),flush=True)
    summary=dict(modules=len(modules),executed_modules=sum('unavailable' not in r for r in rows),
        run=sum(r.get('run',0) for r in rows),failures=sum(r.get('failures',0) for r in rows),
        errors=sum(r.get('errors',int(r.get('exit_code',0)!=0 or r.get('timeout',False))) for r in rows),
        skipped=sum(r.get('skipped',0) for r in rows),elapsed_s=time.monotonic()-start,data_root=str(data),results=rows)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(str(out/'summary.json'),flush=True)
    return int(bool(summary['failures'] or summary['errors']))
if __name__=='__main__':raise SystemExit(main())

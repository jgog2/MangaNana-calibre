"""Compare every rebuilt entry to the qualified source reference."""
import argparse,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def compare(path):
    reference=json.loads((ROOT/'SOURCE_RUNTIME_REFERENCE.json').read_text(encoding='utf8'))
    with zipfile.ZipFile(path) as archive:
        current={n:hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist()}
        info=archive.read('build_info.py').decode()
    expected=reference['entries']
    record=dict(reference_sha256=reference['qualified_zip_sha256'],rebuilt_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        missing=sorted(expected.keys()-current.keys()),extra=sorted(current.keys()-expected.keys()),
        changed=[n for n in expected.keys()&current.keys() if expected[n]!=current[n]],generated_build_info=info)
    record['passed']=not record['missing'] and not record['extra'] and set(record['changed'])<={'build_info.py'}
    return record
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('plugin');args=parser.parse_args()
    result=compare(args.plugin);print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)

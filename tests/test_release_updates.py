import hashlib,importlib.util,io,json,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_updates',ROOT/'app/updates/release_updates.py')
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)

def release(tag='v0.14.1',**kwargs):
    row=dict(tag_name=tag,draft=False,prerelease=False,assets=[dict(name='MangaAnka-0.14.1.zip',size=100,
        browser_download_url='https://github.com/jgog2/MangaNana-calibre/releases/download/'+tag+'/MangaAnka-0.14.1.zip')])
    row.update(kwargs);return row

def package(version='0.14.1',extra=None,identity='MangaNana'):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('version_info.py',"SEMANTIC_VERSION = %r\nCALIBRE_VERSION = %r\n"%(version,tuple(map(int,version.split('.')))))
        z.writestr('__init__.py',"class Plugin:\n    name = %r\n    actual_plugin = 'calibre_plugins.manganana.ui:MangaNanaAction'\n"%identity)
        z.writestr('ui.py','raise RuntimeError("must never execute during validation")')
        z.writestr('plugin-import-name-manganana.txt','')
        if extra:
            info=zipfile.ZipInfo('safe');info.filename=extra[0];z.writestr(info,extra[1])
    raw=stream.getvalue();r=u.select_release([release()], '0.14.0-dev');r['size']=len(raw);r['digest']='sha256:'+hashlib.sha256(raw).hexdigest()
    return raw,r

class ReleaseTests(unittest.TestCase):
    def test_one_point_zero_release_updates_older_build_only(self):
        stable=release('v1.0.0')
        stable['assets'][0].update(name='MangaAnka-v1.0.0.zip',
            browser_download_url='https://github.com/jgog2/MangaNana-calibre/releases/download/v1.0.0/MangaAnka-v1.0.0.zip')
        source=dict(stable['assets'][0],name='MangaAnka-v1.0.0-GitHub-Source.zip')
        stable['assets'].append(source)
        self.assertEqual('1.0.0',u.select_release([stable], '0.14.0-dev')['version'])
        self.assertIsNone(u.select_release([stable], '1.0.0'))
        self.assertIsNone(u.select_release([release()], '1.0.0'))
    def test_new_stable(self):self.assertEqual('0.14.1',u.select_release([release()], '0.14.0-dev')['version'])
    def test_stable_promotes_same_dev(self):self.assertEqual('0.14.0',u.select_release([release('v0.14.0')], '0.14.0-dev')['version'])
    def test_no_downgrade(self):self.assertIsNone(u.select_release([release('v0.13.9')], '0.14.0-dev'))
    def test_no_same_stable(self):self.assertIsNone(u.select_release([release('v0.14.1')], '0.14.1'))
    def test_latest_version_not_api_order(self):self.assertEqual('0.15.0',u.select_release([release('v0.14.1'),release('v0.15.0')], '0.14.0-dev')['version'])
    def test_beta_tag_even_if_latest_flag(self):self.assertIsNone(u.select_release([release('v0.99.0-beta')], '0.14.0-dev'))
    def test_draft_prerelease(self):self.assertIsNone(u.select_release([release(draft=True),release(prerelease=True)], '0.14.0-dev'))
    def test_ambiguous_asset_rejected(self):
        r=release();r['assets']*=2
        with self.assertRaises(ValueError):u.select_release([r], '0.14.0-dev')
    def test_external_url_rejected(self):
        for url in ('http://github.com/jgog2/MangaNana-calibre/releases/download/v1/x.zip','https://github.com/other/repo/releases/download/v1/x.zip','https://github.com.evil/jgog2/MangaNana-calibre/releases/download/v1/x.zip'):
            self.assertFalse(u.official_asset_url(url))
    def test_invalid_list(self):
        with self.assertRaises(ValueError):u.select_release({},'0.14.0-dev')
    def test_valid_package_does_not_execute(self):
        raw,r=package();self.assertIs(raw,u.validate_package(raw,r))
    def test_package_version_mismatch(self):
        raw,r=package('0.14.2')
        with self.assertRaises(ValueError):u.validate_package(raw,r)
    def test_checksum_mismatch(self):
        raw,r=package();r['digest']='sha256:'+'0'*64
        with self.assertRaises(ValueError):u.validate_package(raw,r)
    def test_size_mismatch(self):
        raw,r=package();r['size']+=1
        with self.assertRaises(ValueError):u.validate_package(raw,r)
    def test_unsafe_path(self):
        for path in ('../escape.py','C:/escape.py','/escape.py'):
            raw,r=package(extra=(path,'bad'))
            with self.assertRaises(ValueError):u.validate_package(raw,r)
    def test_wrong_plugin(self):
        raw,r=package(identity='Other')
        with self.assertRaises(ValueError):u.validate_package(raw,r)
    def test_missing_checksum_compatible(self):
        raw,r=package();r['digest']='';self.assertEqual(raw,u.validate_package(raw,r))

if __name__=='__main__':unittest.main(verbosity=2)

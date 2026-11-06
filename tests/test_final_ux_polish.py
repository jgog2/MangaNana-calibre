import copy
import unittest
from calibre_plugins.manganana.app.notifications.completion_policy import successful_batch
from calibre_plugins.manganana.app.updates.release_updates import select_release, current_version
from tests.test_release_updates import release


def ledger():
    return dict(timestamp=1,requested=2,outputs=[dict(status='imported',verified={'book_id':2}),
        dict(status='updated',verified={'book_id':3})],counts={},unexpected=[])


class CompletionPolicyTests(unittest.TestCase):
    def test_all_verified_and_conserved(self):
        self.assertTrue(successful_batch(ledger()))
        self.assertFalse(successful_batch(None))
        for changed in ({'requested':3},{'outputs':[]},{'unexpected':[{}]},
                        {'accounting_error':'disk failure'},{'generation_failures':['chapter']}):
            self.assertFalse(successful_batch(dict(ledger(),**changed)))

    def test_every_non_success_terminal_outcome_is_silent(self):
        for outcome in ('skipped','failed','conflicted','cancelled','pending'):
            row=ledger();row['outputs'][1]['status']=outcome
            self.assertFalse(successful_batch(row),outcome)
        for outcome in ('skipped','failed','conflicted','cancelled'):
            self.assertFalse(successful_batch(dict(ledger(),counts={outcome:1})))

    def test_unverified_import_is_not_a_success_sound(self):
        for evidence in (None,{}, {'book_id':None}):
            row=ledger();row['outputs'][0]['verified']=evidence
            self.assertFalse(successful_batch(row))


class UpdateChannelsTests(unittest.TestCase):
    def test_bounded_transport_timeout_cancel_and_size(self):
        from calibre_plugins.manganana.app.updates import release_updates as policy
        from unittest.mock import patch,MagicMock
        response=MagicMock();response.__enter__.return_value=response;response.headers={}
        opener=MagicMock();opener.open.return_value=response
        with patch.object(policy.urllib.request,'build_opener',return_value=opener),patch.object(policy.time,'monotonic',side_effect=[0,121]):
            with self.assertRaises(TimeoutError):policy.fetch(policy.API_URL,100)
        self.assertEqual(opener.open.call_args.kwargs['timeout'],20)
        with patch.object(policy.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(InterruptedError):policy.fetch(policy.API_URL,100,lambda:True)
        response.headers={'Content-Length':'101'}
        with patch.object(policy.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(ValueError):policy.fetch(policy.API_URL,100)

    def test_channels_versions_and_release_page(self):
        self.assertIsNone(select_release([release('v0.13.9')],'0.14.0-dev'))
        self.assertIsNone(select_release([release('v0.15.0-rc1')],'0.14.0-dev'))
        self.assertIsNone(select_release([release('nonsense')],'0.14.0-dev'))
        self.assertIsNone(select_release([release('v0.15.0',prerelease=True)],'0.14.0-dev'))
        self.assertIsNone(select_release([release('v0.14.0')],'0.14.0'))
        self.assertEqual(select_release([release('v0.14.0')],'0.14.0-dev')['version'],'0.14.0')
        r=select_release([release('v0.14.1')],'0.14.0-dev')
        self.assertEqual(r['notes_url'],'https://github.com/jgog2/MangaNana-calibre/releases/tag/v0.14.1')
        with self.assertRaises(ValueError):current_version('broken')


class DisplayPolicyTests(unittest.TestCase):
    def test_screen_and_scale_matrix(self):
        # Pure policy only; these are not claims of physical monitor testing.
        import importlib.util,types,sys
        from pathlib import Path
        import ast
        tree=ast.parse((Path(__file__).resolve().parents[1]/'presentation/interface_scale.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='scale_factor')
        namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),'scale policy','exec'),namespace)
        factor=namespace['scale_factor']
        from calibre_plugins.manganana.presentation.window_geometry import choose_window_size, clamp_window_position
        for physical in ((1366,768),(1920,1080),(2560,1440),(3840,2160)):
            for dpi in (1,1.25,1.5,1.75,2):
                available=tuple(int(n/dpi) for n in physical)
                size=choose_window_size(None,available)
                self.assertTrue(all(size[i]<=available[i] for i in (0,1)))
                self.assertIn(factor('auto',100,available),(.9,1.))
                self.assertEqual(factor('manual',115,available),1.15)
                pos=clamp_window_position((-5000,-5000),size,(-available[0],0,*available))
                self.assertGreaterEqual(pos[0],-available[0]);self.assertGreaterEqual(pos[1],0)
        self.assertEqual(factor('manual','invalid',(1920,1080)),1.)
        self.assertEqual(factor('manual',200,(1920,1080)),1.15)


if __name__=='__main__':unittest.main()

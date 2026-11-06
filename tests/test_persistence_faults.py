"""Storage failure controls; no production profiles or real disk exhaustion."""
import errno
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from tools.source_bootstrap import ensure_source_package
ensure_source_package()
from calibre_plugins.manganana.discovery import saved_manga as saved


def listing(identity):
    return dict(source_id='mangapill',id=identity,title='Fixture '+identity,
                url='https://mangapill.com/manga/'+identity)


class PersistenceFaults(unittest.TestCase):
    def test_disk_full_before_fsync_preserves_old_commit_and_pending_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            first=saved.FavoritesStore(directory);first.toggle(listing('1'));self.assertTrue(first.close())
            before=first.path.read_bytes()
            store=saved.FavoritesStore(directory)
            with patch.object(saved.os,'fsync',side_effect=OSError(errno.ENOSPC,'Controlled disk full')):
                store.toggle(listing('2'));self.assertFalse(store.close())
            self.assertEqual(before,first.path.read_bytes())
            self.assertFalse(list(first.path.parent.glob('.manganana-favorites-*')))
            self.assertTrue(store.contains(listing('2')))
            retry=saved.FavoritesStore(directory);self.assertTrue(retry.close())
            self.assertEqual(2,len(json.loads(first.path.read_bytes())['records']))

    def test_replace_permission_failure_retains_exact_durable_edit_and_warns_on_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            store=saved.FavoritesStore(directory)
            with patch.object(saved.os,'replace',side_effect=PermissionError('Controlled permission failure')):
                store.toggle(listing('1'));self.assertFalse(store.close())
            paths=list(store.recovery_paths);self.assertEqual(1,len(paths))
            self.assertIn(paths[0],store.error)
            # Simulate a fresh process reader without the in-process owner map.
            independent=saved._FavoritesState(directory)
            self.assertIn('interrupted',independent.warning)
            self.assertEqual({},independent.records)
            self.assertEqual('1',json.loads(Path(paths[0]).read_bytes())['records'][0]['listing']['id'])
            retry=saved.FavoritesStore(directory);self.assertTrue(retry.close())
            self.assertFalse(Path(paths[0]).exists())

    @unittest.skipUnless(sys.platform=='win32','Actual Windows sharing violation control')
    def test_actual_locked_destination_preserves_recoverable_edits(self):
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        with tempfile.TemporaryDirectory() as directory:
            first=saved.FavoritesStore(directory);first.toggle(listing('1'));self.assertTrue(first.close())
            before=first.path.read_bytes();store=saved.FavoritesStore(directory)
            handle=kernel.CreateFileW(str(first.path),0x80000000,0,None,3,0,None)
            self.assertNotEqual(ctypes.c_void_p(-1).value,handle)
            try:
                store.toggle(listing('2'));self.assertFalse(store.close())
                self.assertTrue(store.recovery_paths)
            finally: kernel.CloseHandle(handle)
            self.assertEqual(before,first.path.read_bytes())
            retry=saved.FavoritesStore(directory);self.assertTrue(retry.close())
            self.assertEqual(2,len(json.loads(first.path.read_bytes())['records']))


if __name__=='__main__':unittest.main()

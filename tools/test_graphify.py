import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('local_graphify', Path(__file__).with_name('graphify.py'))
graphify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graphify)


class ProvenanceTests(unittest.TestCase):
    def test_wrong_commit_or_dangling_edge_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            commit = 'a' * 40
            graph = {'nodes': [{'id': 'a'}], 'edges': [], 'built_at_commit': commit}
            def write():
                (out / 'graph.json').write_text(json.dumps(graph), encoding='utf-8')
            (out / 'GRAPH_REPORT.md').write_text(f'Built from commit: `{commit[:8]}`', encoding='utf-8')
            (out / 'graph.html').write_text('<html></html>', encoding='utf-8')
            write()
            self.assertEqual(graphify.validate(out, commit), (1, 0))
            with self.assertRaisesRegex(ValueError, 'commit'):
                graphify.validate(out, 'b' * 40)
            graph['edges'] = [{'source': 'a', 'target': 'missing'}]
            write()
            with self.assertRaisesRegex(ValueError, 'dangling'):
                graphify.validate(out, commit)


class RetentionTests(unittest.TestCase):
    def owned_backup(self, root, name):
        backup = root / name
        backup.mkdir()
        (backup / 'provenance.json').write_text(json.dumps({'producer': graphify.PRODUCER}), encoding='utf-8')
        return backup

    def test_retention_keeps_newest_and_ignores_unmarked_user_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            older = self.owned_backup(root, 'previous-build-old')
            newer = self.owned_backup(root, 'previous-build-new')
            user = root / 'previous-build-user'
            user.mkdir()
            os.utime(older, ns=(1_600_000_000_000_000_000,) * 2)
            os.utime(newer, ns=(1_700_000_000_000_000_000,) * 2)
            self.assertEqual(graphify.retain_latest_backup(root), newer)
            self.assertTrue(newer.is_dir())
            self.assertFalse(older.exists())
            self.assertTrue(user.is_dir())

    def test_publication_retains_last_good_graph_if_rename_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = self.owned_backup(root, 'graphify-out')
            (current / 'sentinel').write_text('last-good', encoding='utf-8')
            staged = root / 'build-new' / 'graphify-out'
            staged.mkdir(parents=True)
            original = Path.rename
            def rename(path, destination):
                if path == staged:
                    raise OSError('fixture publication failure')
                return original(path, destination)
            with patch.object(Path, 'rename', rename), self.assertRaises(OSError):
                graphify._publish_graph(staged, root)
            self.assertEqual((current / 'sentinel').read_text(), 'last-good')

    def test_repeated_publications_keep_one_managed_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for i in range(4):
                staging = root / f'build-{i}'
                staging.mkdir()
                out = self.owned_backup(staging, 'graphify-out')
                graphify._publish_graph(out, root)
                backups = list(root.glob('previous-build-*'))
                self.assertEqual(len(backups), min(i, 1))
            self.assertTrue((root / 'previous-build-3').is_dir())

    def test_reparse_points_are_recognized_without_following_them(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(graphify.stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400, create=True):
            self.assertTrue(graphify._is_linklike(info))

    def test_symlinked_backup_and_nested_links_are_never_removed(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root, target = Path(temporary), Path(external)
            (target / 'sentinel').write_text('keep', encoding='utf-8')
            old = self.owned_backup(root, 'previous-build-old')
            newest = self.owned_backup(root, 'previous-build-new')
            try:
                (root / 'previous-build-link').symlink_to(target, target_is_directory=True)
                (old / 'nested').symlink_to(target, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f'symlink creation unavailable: {error}')
            graphify.retain_latest_backup(root, preferred=newest)
            self.assertTrue(old.is_dir())
            self.assertTrue((root / 'previous-build-link').is_symlink())
            self.assertEqual((target / 'sentinel').read_text(), 'keep')

    @unittest.skipUnless(os.name == 'nt', 'Windows directory junction coverage')
    def test_windows_junctions_leave_external_contents_untouched(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root, target = Path(temporary), Path(external)
            (target / 'sentinel').write_text('keep', encoding='utf-8')
            old = self.owned_backup(root, 'previous-build-old')
            newest = self.owned_backup(root, 'previous-build-new')
            links = [root / 'previous-build-junction', old / 'nested-junction']
            try:
                for link in links:
                    path_arg = str(link).replace("'", "''")
                    target_arg = str(target).replace("'", "''")
                    subprocess.run(['powershell', '-NoProfile', '-Command',
                        f"$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path '{path_arg}' -Target '{target_arg}' | Out-Null"], check=True)
                graphify.retain_latest_backup(root, preferred=newest)
                self.assertTrue(old.is_dir())
                self.assertTrue(links[0].exists())
                self.assertEqual((target / 'sentinel').read_text(), 'keep')
            finally:
                # Remove only the junction entries, never recurse into their targets.
                for link in links:
                    if os.path.lexists(link):
                        os.rmdir(link)


if __name__ == '__main__':
    unittest.main()

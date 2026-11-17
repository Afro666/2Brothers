import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()

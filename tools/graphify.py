"""Build a local-only code graph with verified source provenance. Requires uv."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

VERSION = '0.9.106'
PRODUCER = 'tools/graphify.py'
BACKUP_PREFIX = 'previous-build-'


def _is_linklike(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def _is_tool_backup(path, root):
    if not path.name.startswith(BACKUP_PREFIX):
        return False
    try:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or _is_linklike(info):
            return False
        if path.parent.resolve(strict=True) != root or path.resolve(strict=True).parent != root:
            return False
        provenance = path / 'provenance.json'
        info = provenance.lstat()
        if not stat.S_ISREG(info.st_mode) or _is_linklike(info):
            return False
        data = json.loads(provenance.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get('producer') == PRODUCER


def _contains_linklike(path):
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    info = Path(entry.path).lstat()
                    if _is_linklike(info):
                        return True
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(Path(entry.path))
        except OSError:
            return True
    return False


def _remove_tool_backup(path, root):
    if not _is_tool_backup(path, root) or _contains_linklike(path):
        return False
    # Verify the absolute direct-child target again immediately before recursive
    # removal. Never remove links, junctions, or a backup containing any of them.
    resolved = path.resolve(strict=True)
    if resolved.parent != root or _is_linklike(path.lstat()):
        return False
    shutil.rmtree(path)
    return True


def retain_latest_backup(output_root, *, preferred=None):
    root = output_root.resolve()
    backups = [path for path in root.iterdir() if _is_tool_backup(path, root)]
    if not backups:
        return None
    preferred = preferred.resolve() if preferred is not None else None
    keep = next((path for path in backups if path.resolve() == preferred), None)
    if keep is None:
        keep = max(backups, key=lambda path: path.lstat().st_mtime_ns)
    for path in backups:
        if path != keep:
            _remove_tool_backup(path, root)
    return keep


def _publish_graph(out, output_root):
    destination = output_root / 'graphify-out'
    previous = None
    try:
        if os.path.lexists(destination):
            info = destination.lstat()
            if _is_linklike(info) or not stat.S_ISDIR(info.st_mode):
                raise ValueError('Refusing to replace a graph destination that is not an ordinary directory')
            previous = output_root / ('previous-' + out.parent.name)
            if os.path.lexists(previous):
                raise ValueError('Backup destination already exists')
            destination.rename(previous)
        out.rename(destination)
    except BaseException:
        if previous is not None and os.path.lexists(previous) and not os.path.lexists(destination):
            previous.rename(destination)
        raise
    retain_latest_backup(output_root, preferred=previous)
    return destination


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()


def source_revision(source):
    if Path(git(source, 'rev-parse', '--show-toplevel')).resolve() != source.resolve():
        raise ValueError('--source must be a repository root')
    if git(source, 'status', '--porcelain'):
        raise ValueError('Source must be clean; commit changes or use an isolated clean worktree.')
    return git(source, 'rev-parse', 'HEAD'), git(source, 'rev-parse', 'HEAD^{tree}')


def validate(out, commit):
    graph = json.loads((out / 'graph.json').read_text(encoding='utf-8'))
    ids = {node['id'] for node in graph['nodes']}
    edges = graph.get('links', graph.get('edges', []))
    if not ids or len(ids) != len(graph['nodes']):
        raise ValueError('Graph is empty or has duplicate node IDs')
    if any(e['source'] not in ids or e['target'] not in ids for e in edges):
        raise ValueError('Graph has dangling relationships')
    if graph.get('built_at_commit') != commit:
        raise ValueError('Graph commit differs from the extracted source')
    report = (out / 'GRAPH_REPORT.md').read_text(encoding='utf-8')
    if f'Built from commit: `{commit[:8]}`' not in report:
        raise ValueError('Report commit differs from the extracted source')
    if not (out / 'graph.html').is_file():
        raise ValueError('Interactive graph was not produced')
    return len(ids), len(edges)


def build(source, output_root, *, obsidian=False):
    source, output_root = source.resolve(), output_root.resolve()
    commit, tree = source_revision(source)
    uv = shutil.which('uv')
    if not uv:
        raise ValueError('Install uv first; it runs pinned Graphify in an isolated environment.')
    output_root.mkdir(parents=True, exist_ok=True)
    # Fresh staging prevents old graphs/semantic layers or manifests being relabeled
    # as the current source. The previous published graph survives a failed build.
    with tempfile.TemporaryDirectory(prefix='build-', dir=output_root) as temporary:
        staging = Path(temporary).resolve()
        if staging.parent != output_root:
            raise ValueError('Unexpected staging directory')
        def run(*args, cwd):
            subprocess.run([uv, 'tool', 'run', '--from', f'graphifyy=={VERSION}',
                            'graphify', *map(str, args)], cwd=cwd, check=True)
        run('extract', source, '--code-only', '--no-cluster', '--out', staging, cwd=source)
        if source_revision(source) != (commit, tree):
            raise ValueError('Source changed during extraction')
        out = staging / 'graphify-out'
        path = out / 'graph.json'
        graph = json.loads(path.read_text(encoding='utf-8'))
        # The raw extractor does not stamp this itself; cluster-only otherwise
        # derives the commit from the output directory's parent checkout.
        graph['built_at_commit'] = commit
        path.write_text(json.dumps(graph, ensure_ascii=False), encoding='utf-8')
        run('cluster-only', staging, '--no-label', cwd=staging)
        if obsidian:
            run('export', 'obsidian', '--graph', path, '--dir', out / 'obsidian', cwd=staging)
        nodes, edges = validate(out, commit)
        if source_revision(source) != (commit, tree):
            raise ValueError('Source changed before graph publication')
        provenance = {'source_root': str(source), 'source_commit': commit,
                      'source_tree': tree, 'source_clean': True,
                      'graphify_version': VERSION, 'producer': PRODUCER,
                      'nodes': nodes, 'relationships': edges,
                      'generated_at': datetime.now(timezone.utc).isoformat(),
                      'mode': 'local code-only; no model API or LLM labels'}
        (out / 'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
        destination = _publish_graph(out, output_root)
    print(f'Graph verified: {commit[:8]}, {nodes} nodes, {edges} relationships: {destination}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument('--source', type=Path, default=root)
    parser.add_argument('--out', type=Path, default=root / '.local' / 'graphify')
    parser.add_argument('--obsidian', action='store_true')
    args = parser.parse_args()
    build(args.source, args.out, obsidian=args.obsidian)


if __name__ == '__main__':
    main()

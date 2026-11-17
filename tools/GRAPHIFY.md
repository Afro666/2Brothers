# Local code graph

Install uv, then run this from a clean project checkout:

```powershell
python tools/graphify.py
```

The helper runs pinned `graphifyy==0.9.106` in an isolated uv environment. It uses
local AST extraction and disables LLM community labeling; no model API is called.
Open `.local/graphify/graphify-out/graph.html`, read `GRAPH_REPORT.md`, or query the
full `graph.json` with Graphify. Large HTML graphs use a community overview.

For a dirty working checkout, select a separate clean checkout explicitly:

```powershell
python tools/graphify.py --source S:/GitHub/2Brothers/.local/graphify/source
```

`--out` selects the output parent; `--obsidian` also creates a node-level vault.
Builds stage fresh output, check the source stays unchanged, and verify graph/report
metadata against its real commit before publication. `provenance.json` records the
source root, commit, Git tree, graph counts and this tool as producer. After successful
publication only the most recent managed `previous-build-*` backup is retained.
Unmarked legacy/user directories and backups containing symlinks, junctions or other
reparse points are never pruned. Failed publication restores the last good current graph.
Do not treat static graph links as a complete runtime call trace or infer current
application behavior from a graph whose provenance names another revision.

Generated output stays under the ignored `.local/`. Documentation and media are
not semantically indexed. `nemotron_test` is also ignored and remains local.

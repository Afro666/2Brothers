#!/usr/bin/env bash
# loop.sh: every 4 minutes, gate each open ai-fix PR whose head was not tried yet.
# HOURS (default 9) bounds the run; GATE_ORDER=-r works newest first (for a second gate).
# Run from the main checkout. Results: $GATE_LOG/night-log.txt.
HERE=$(cd "$(dirname "$0")" && pwd)
LOG=${GATE_LOG:-${TMPDIR:-/tmp}/merge-queue}; mkdir -p "$LOG"
TRIED=$LOG/tried.txt; NIGHT=$LOG/night-log.txt
REPO=${GATE_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}
touch "$TRIED" "$NIGHT"
end=$(( $(date +%s) + ${HOURS:-9} * 3600 ))
while [ "$(date +%s)" -lt "$end" ]; do
  list=$(gh pr list -R "$REPO" --state open --limit 100 --json number,headRefName,headRefOid \
    --jq '.[]|select(.headRefName|startswith("ai-fix/"))|"\(.number) \(.headRefOid)"' 2>/dev/null | sort -n ${GATE_ORDER:-})
  while read -r n sha; do
    [ -z "$n" ] && continue
    grep -q "^$sha$" "$TRIED" && continue
    out=$(bash "$HERE/gate.sh" "$n" 2>&1)
    echo "$(date +%H:%M) $out" | tr '\n' ' ' >> "$NIGHT"; echo >> "$NIGHT"
    echo "$out" | grep -Eq "MERGE: Pull Request successfully merged|CONFLICT|RED:|tsc failed" && echo "$sha" >> "$TRIED"
    echo "$out" | grep -E "MERGE: Pull Request successfully merged|CONFLICT|RED:" | sed "s/^/$(date +%H:%M) /"
  done <<< "$list"
  sleep 240
done
echo "gate loop ended"

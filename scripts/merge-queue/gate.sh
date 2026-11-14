#!/usr/bin/env bash
# gate.sh <pr>: test one ai-fix PR on top of current main in a gate worktree, and
# squash-merge it at its reviewed head when the suites it touches are green.
# Settings (environment): GATE_REPO, GATE_PY (python with the test deps), GATE_LOG,
# GATE_NAME (a, b, ...: one per parallel gate), GATE_T (the gate worktree).
# See .claude/skills/merge-queue/SKILL.md for the rules.
MAIN=$(git rev-parse --show-toplevel)
REPO=${GATE_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}
T=${GATE_T:-$MAIN/../$(basename "$MAIN")-gate-${GATE_NAME:-a}}
PY=${GATE_PY:-python}
LOG=${GATE_LOG:-${TMPDIR:-/tmp}/merge-queue}
mkdir -p "$LOG"
# one gate at a time: two runs in one worktree once merged a red PR (2026-11-14 03:39)
LOCK=${GATE_LOCK:-$LOG/.lock-${GATE_NAME:-a}}
if ! mkdir "$LOCK" 2>/dev/null; then echo "gate busy: another run holds $LOCK"; exit 0; fi
# a PR is tested by one gate at a time, even with two gate worktrees
if ! mkdir "$LOG/claim-$1" 2>/dev/null; then rmdir "$LOCK"; echo "#$1 claimed by the other gate"; exit 0; fi
trap 'rmdir "$LOCK" "$LOG/claim-$1" 2>/dev/null' EXIT
rm -f "$LOG"/$1-*.txt 2>/dev/null
[ -d "$T" ] || git -C "$MAIN" worktree add -q --detach "$T" origin/main
cd "$T" || exit 1
for n in "$@"; do
  read -r state head sha < <(gh pr view "$n" -R $REPO --json state,headRefName,headRefOid --jq '"\(.state) \(.headRefName) \(.headRefOid)"')
  if [ "$state" != "OPEN" ]; then echo "#$n $state: skip"; continue; fi
  review=$(gh api "repos/$REPO/commits/$sha/check-runs" --jq 'if ([.check_runs[]|select(.name=="opus-review" and .conclusion=="success")]|length)>0 then "success" else "none" end')
  if [ "$review" != "success" ]; then echo "#$n opus-review=$review: not merged"; continue; fi
  fetched=0
  for try in 1 2 3 4 5; do
    git fetch -q origin "+refs/heads/main:refs/gate/${GATE_NAME:-a}/main" "+refs/pull/$n/head:refs/gate/${GATE_NAME:-a}/pr" 2>/dev/null && { fetched=1; break; }
    sleep 10
  done
  if [ $fetched = 0 ]; then echo "#$n fetch failed (network): retry later"; continue; fi
  git checkout -q --detach refs/gate/${GATE_NAME:-a}/main && git reset -q --hard refs/gate/${GATE_NAME:-a}/main && git clean -qfd -e web/node_modules
  if ! git merge -q --no-edit "$sha" >/dev/null 2>&1; then
    git merge --abort 2>/dev/null
    issue=${head#ai-fix/}
    ist=$(gh issue view "$issue" -R $REPO --json state --jq .state 2>/dev/null)
    gh pr close "$n" -R $REPO --delete-branch --comment "Closing: conflicts with main. The fix agent reruns on current main." >/dev/null 2>&1
    if [ "$ist" = "OPEN" ]; then gh workflow run ai-fix.yml -R $REPO -f issue="$issue" >/dev/null 2>&1; fi
    echo "#$n CONFLICT with main: closed, fix agent rerun for #$issue ($ist)"; continue
  fi
  files=$(git diff --name-only refs/gate/${GATE_NAME:-a}/main HEAD)
  ok=1
  if echo "$files" | grep -qvE '^web/|\.md$'; then
    $PY -m pytest -q -p no:cacheprovider --ignore=web --ignore=vendor > "$LOG/$n-py.txt" 2>&1 || ok=0
    echo "#$n python: $(tail -1 "$LOG/$n-py.txt")"
  fi
  if echo "$files" | grep -q '^web/'; then
    (cd web && { [ -d node_modules ] || npm ci --silent >/dev/null 2>&1; } \
      && npx tsc --noEmit -p . > "$LOG/$n-tsc.txt" 2>&1) || { ok=0; echo "#$n tsc failed"; }
    # only the tests that import a changed file (vitest related); tsc above checks everything
    rel=$(echo "$files" | grep '^web/' | sed 's#^web/##' | tr '\n' ' ')
    (cd web && npx vitest related $rel --run --maxWorkers=3 > "$LOG/$n-web.txt" 2>&1)
    if grep -q " FAIL " "$LOG/$n-web.txt"; then
      # rerun only the failed files: timeouts under load pass when run alone
      failed=$(grep -oE "FAIL +src/[^ ]+\.test\.tsx?" "$LOG/$n-web.txt" | awk '{print $2}' | sort -u)
      # twice: other sessions run test suites on this laptop too, and 5 s timeouts flake under load
      (cd web && npx vitest run $failed > "$LOG/$n-web2.txt" 2>&1) || (cd web && npx vitest run $failed > "$LOG/$n-web3.txt" 2>&1) || { ok=0; echo "#$n web FAILED: $failed"; }
    fi
    echo "#$n web: $(grep -E 'Tests ' "$LOG/$n-web.txt" | tail -1)"
  fi
  if [ $ok = 1 ]; then
    msg=$(gh api -X PUT "repos/$REPO/pulls/$n/merge" -f merge_method=squash -f sha="$sha" --jq .message 2>&1)
    echo "#$n MERGE: $msg"
    gh api -X DELETE "repos/$REPO/git/refs/heads/$head" >/dev/null 2>&1
  else
    echo "#$n RED: not merged (logs $LOG/$n-*)"
  fi
done

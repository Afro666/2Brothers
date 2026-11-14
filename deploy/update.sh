#!/bin/sh
# Runs on the server as the forced command of the deploy SSH key, so that key
# can do nothing else. The commit to deploy arrives as the SSH command text.
set -eu

sha="${SSH_ORIGINAL_COMMAND:-}"
if ! printf '%s' "$sha" | grep -Eq '^[0-9a-f]{40}$'; then
	echo "expected a 40-character commit sha" >&2
	exit 2
fi

# One deploy at a time: a second one waits here instead of building over the first.
exec 9>/var/lock/2brothers-deploy.lock
flock 9

# A person can pause deploys (a recording, a long job on the server):
# touch /opt/2brothers.hold to pause, rm it to resume. The next deploy catches up.
if [ -e /opt/2brothers.hold ]; then
	echo "deploys are on hold (/opt/2brothers.hold exists); $sha was not deployed"
	exit 0
fi

cd /opt/2brothers
git fetch --quiet origin main
if ! git merge-base --is-ancestor "$sha" origin/main; then
	echo "$sha is not on main" >&2
	exit 2
fi
# Deploy the newest commit on main, not the one that started this run: when merges land
# back to back, the first run deploys them all and the next runs find nothing to do, so the
# site restarts once instead of once per merge.
head=$(git rev-parse origin/main)
if [ "$(cat /opt/2brothers.deployed 2>/dev/null)" = "$head" ]; then
	echo "$head is already deployed"
	exit 0
fi
# This checkout is only for deploys: drop anything that is not the commit
# (ignored files such as .env stay), so the image is built from the commit alone.
git checkout --quiet --force --detach "$head"
git clean --quiet -fd

# compose recreates a container only when its image or settings changed, so a web-only
# commit leaves the gateway and the buyer running.
docker compose --env-file /opt/2brothers/.env -f deploy/compose.yaml up -d --build --remove-orphans
docker image prune -f >/dev/null
# Mark the commit as deployed only once the gateway answers; if it never does, the run fails
# and the next one tries again.
tries=0
until docker compose --env-file /opt/2brothers/.env -f deploy/compose.yaml exec -T gateway \
	python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" 2>/dev/null; do
	tries=$((tries + 1))
	if [ "$tries" -ge 30 ]; then
		echo "the gateway did not answer /health after the deploy" >&2
		exit 1
	fi
	sleep 2
done
# Outside the checkout, so git clean leaves it.
echo "$head" > /opt/2brothers.deployed
echo "deployed $head (run started by $sha)"

#!/bin/sh
# Runs on the server as the forced command of the deploy SSH key, so that key
# can do nothing else. The commit to deploy arrives as the SSH command text:
# "<sha>", or "force <sha>" to deploy even when that commit is already deployed.
set -eu

sha="${SSH_ORIGINAL_COMMAND:-}"
force=no
case "$sha" in
"force "*)
	force=yes
	sha=${sha#force }
	;;
esac
# The whole value, not one line of it: only hex digits, exactly 40 of them.
case "$sha" in
"" | *[!0-9a-f]*)
	echo "expected a 40-character commit sha" >&2
	exit 2
	;;
esac
if [ "${#sha}" -ne 40 ]; then
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
if [ "$force" = no ] && [ "$(cat /opt/2brothers.deployed 2>/dev/null)" = "$head" ]; then
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
# The site itself (#213): Caddy exits at once on a bad Caddyfile or SITE_ADDRESS, and the
# job must fail then. Wait until web runs, then look again: a crash loop is "restarting".
web_running() {
	docker compose --env-file /opt/2brothers/.env -f deploy/compose.yaml ps --status running --services 2>/dev/null |
		grep -qx web
}
tries=0
until web_running; do
	tries=$((tries + 1))
	if [ "$tries" -ge 15 ]; then
		echo "the web container is not running after the deploy" >&2
		exit 1
	fi
	sleep 2
done
sleep 5
if ! web_running; then
	echo "the web container stopped right after the deploy (check the Caddyfile and SITE_ADDRESS)" >&2
	exit 1
fi
# Outside the checkout, so git clean leaves it.
echo "$head" > /opt/2brothers.deployed
echo "deployed $head (run started by $sha)"

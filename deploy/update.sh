#!/bin/sh
# Runs on the server as the forced command of the deploy SSH key, so that key
# can do nothing else. The commit to deploy arrives as the SSH command text.
set -eu

sha="${SSH_ORIGINAL_COMMAND:-}"
if ! printf '%s' "$sha" | grep -Eq '^[0-9a-f]{40}$'; then
	echo "expected a 40-character commit sha" >&2
	exit 2
fi

cd /opt/2brothers
git fetch --quiet origin main
if ! git merge-base --is-ancestor "$sha" origin/main; then
	echo "$sha is not on main" >&2
	exit 2
fi
# This checkout is only for deploys: drop anything that is not the commit
# (ignored files such as .env stay), so the image is built from the commit alone.
git checkout --quiet --force --detach "$sha"
git clean --quiet -fd

docker compose --env-file /opt/2brothers/.env -f deploy/compose.yaml up -d --build --remove-orphans
docker image prune -f >/dev/null
echo "deployed $sha"

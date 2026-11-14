# deploy: the app on the Verda instance

Every push to `main` that touches `web/` or `deploy/` runs
`.github/workflows/deploy.yml`. The workflow connects to the server over SSH
with a key that can only run `deploy/update.sh`. That script checks the commit
is on `main`, checks it out in `/opt/2brothers`, and runs Docker Compose
(`deploy/compose.yaml`). The server builds the images itself; there is no
registry.

The stack is two containers. `web` is Caddy: it serves the built web app and is the only
thing reachable from outside. `gateway` is the FastAPI gateway (`gateway/Dockerfile`),
reached only through Caddy. MongoDB stays on Atlas.

| Path | Who | Protection |
|---|---|---|
| `/api/ping` | monitors | none; answers `{"status":"ok"}` |
| `/gateway/*` | the Buyer agent, other services | the caller's own bearer token, checked by the gateway |
| `/api/*` | the web app | open to anyone with the link; Caddy adds the gateway's human token on the server, so it never reaches a browser. The web app names the person in `X-User`. |
| everything else | the screens | none |

## Settings

Server file `/opt/2brothers/.env` (mode 600, not in git; never in an image):

```
SITE_ADDRESS="<ip-with-dashes>.sslip.io, http://<ip>"
GATEWAY_HUMAN_TOKEN=<long random string>
GATEWAY_AGENT_TOKEN=<another long random string; give this one to the Buyer agent>
VALIO_API_KEY=<key>
MONGODB_URI="<Atlas connection string>"
```

Keep the single quotes around the hash: it contains `$` signs. Compose refuses to start
when a required value is missing.

A host name gets HTTPS from Caddy automatically; `sslip.io` gives the IP a
host name without buying a domain. The `http://<ip>` part keeps plain HTTP on
the bare IP.

GitHub secrets (repo settings, names only here):

| Secret | What |
|---|---|
| `DEPLOY_SSH_KEY` | Private half of the deploy-only key |
| `DEPLOY_HOST` | The instance's IP |
| `DEPLOY_KNOWN_HOSTS` | The server's SSH host key line (`ssh-keyscan -t ed25519 <ip>`) |

## One-time server setup (as root)

```
apt-get update && apt-get install -y docker.io docker-compose-v2 git
git clone https://github.com/Afro666/2Brothers.git /opt/2brothers
install -m 600 /dev/null /opt/2brothers/.env
printf 'SITE_ADDRESS="%s"\n' "<ip-with-dashes>.sslip.io, http://<ip>" >> /opt/2brothers/.env
echo 'restrict,command="/opt/2brothers/deploy/update.sh" <deploy public key>' >> /root/.ssh/authorized_keys
```

Ports 22, 80 and 443 must be open.

## Check or redo a deploy

- Run it by hand: GitHub, Actions, `deploy`, "Run workflow".
- On the server (the settings file is needed for every compose command):
  `docker compose --env-file /opt/2brothers/.env -f /opt/2brothers/deploy/compose.yaml ps`,
  and the same with `logs web` or `logs gateway`.
- Try the image locally: `docker build -t web web` then
  `docker compose --env-file <your .env> -f deploy/compose.yaml up --build` (it needs the values above).
The internal Nemotron `buyer` worker (#279) uses the same application image with
the `two-brothers-buyer-worker` entrypoint. Set `VERDA_INFERENCE_KEY` in the server
`.env` for this service. The key is optional for compose: without it web and gateway
still deploy, and the buyer returns 503 `BUYER_UNAVAILABLE` until the key is set. It receives the agent token and Mongo URI,
not the human token or upstream Valio key. No worker port is published.
`BUYER_WORKER_URL` on the gateway routes free-text proposal requests to it.

## One deploy at a time, and pausing deploys

- Deploys never overlap: the workflow queues runs (`concurrency: deploy`) and `deploy/update.sh`
  takes a lock on the server, so a second deploy waits for the first.
- Every deploy rebuilds and restarts the containers, which cuts off requests in flight. To pause
  deploys (recording the demo, a long job on the server): `touch /opt/2brothers.hold` on the
  server. Merges still pass; their deploy run says "on hold" and changes nothing. `rm
  /opt/2brothers.hold` to resume; the next merge, or "Run workflow" on the deploy action, deploys
  the newest commit.

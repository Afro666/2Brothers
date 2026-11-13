# deploy: the app on the Verda instance

Every push to `main` that touches `web/` or `deploy/` runs
`.github/workflows/deploy.yml`. The workflow connects to the server over SSH
with a key that can only run `deploy/update.sh`. That script checks the commit
is on `main`, checks it out in `/opt/2brothers`, and runs Docker Compose
(`deploy/compose.yaml`). The server builds the images itself; there is no
registry.

Today the stack is one container: Caddy serving the built web app. The
gateway container and the `/api` route are added when the gateway has an HTTP
server. MongoDB stays on Atlas.

## Settings

Server file `/opt/2brothers/.env` (not in git; keys such as `MONGODB_URI` go
here later, never in an image):

```
SITE_ADDRESS="<ip-with-dashes>.sslip.io, http://<ip>"
```

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
- On the server: `docker compose -f /opt/2brothers/deploy/compose.yaml ps` and
  `... logs web`.
- Try the image locally: `docker build -t web web` then
  `docker run -p 8080:80 -e SITE_ADDRESS=:80 web`.

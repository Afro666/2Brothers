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
- A deploy always takes the newest commit on main and writes its sha to `/opt/2brothers.deployed`;
  a run that finds that commit already deployed does nothing. Merges that land back to back
  usually cause one restart instead of one each. The sha is written only after the gateway
  answers `/health`. To redeploy the same commit (after editing `/opt/2brothers/.env`, or a
  crashed container): "Run workflow" on the deploy action; a manual run always deploys.
- Only what changed restarts: a web-only commit rebuilds the web image and leaves the gateway and
  the buyer running. While the gateway restarts, Caddy holds a request for up to 15 seconds
  instead of answering 502.
- A deploy that changes the gateway restarts it, which cuts off requests in flight. To pause
  deploys (recording the demo, a long job on the server): `touch /opt/2brothers.hold` on the
  server. Merges still pass; their deploy run says "on hold" and changes nothing. `rm
  /opt/2brothers.hold` to resume; the next merge, or "Run workflow" on the deploy action, deploys
  the newest commit.

## Recall check (Context.dev)

- `CONTEXT_DEV_API_KEY` in the server `.env` is optional. With it, "Check recalls now"
  (`POST /v1/kitchens/{k}/recalls/check`) scrapes the Ruokavirasto list live, one call per
  check. Without it, or when Context.dev is slow or down, the check uses the recording in
  the image and the screen says "recording". `RECALL_CHECK_TIMEOUT_S` (default 45, at most
  120) bounds the call; a live list scrape took 30 seconds on 2026-11-14.
- The demo needs an open proposal with the recalled coffee (461332) before the check. On
  the server:
  `docker compose --env-file /opt/2brothers/.env -f /opt/2brothers/deploy/compose.yaml exec gateway python -m demo.recall_demo`
  It makes a READY proposal through the gateway and orders nothing. Run it before the first
  check: after a check has recorded the recall, new quotes leave the coffee out and the
  command says so.

## Switch sign-in on (and off again)

Default is the open demo: anyone with the link is the demo person and can approve. To close it:

1. On the server, edit `/opt/2brothers/.env` and add three lines (type the values there, never in chat or git):

   ```
   GATEWAY_REQUIRE_LOGIN=true
   DEMO_USER_EMAIL=<the approver's email>
   DEMO_USER_PASSWORD='<at least 10 characters, single-quoted>'
   ```

2. Restart the gateway with the new settings:

   ```
   cd /opt/2brothers
   docker compose --env-file .env -f deploy/compose.yaml up -d gateway
   ```

3. Open the site: it sends you to `/sign-in`. The first sign-in with the email and password
   above creates that approver account.
4. A read-only account for judges (it asks for the password twice, nothing is echoed):

   ```
   docker compose --env-file .env -f deploy/compose.yaml run --rm --no-deps gateway python -m gateway.users add --email <judge email> --role viewer
   ```

   `--role` is `approver`, `chef` (may ask for orders) or `viewer` (reads only). `python -m gateway.users list` shows the accounts, `remove --email` deletes one.
5. The account for the stage. An account belongs to one kitchen, and a kitchen's account is
   refused Valio's pages (Demand, the Valio view on Home: "a kitchen's session cannot read a
   supplier's view"). The approver from step 3 is such an account. For the demo, make one
   approver with `--kitchen all`: it sees what the open demo's person sees, behind a sign-in.

   ```
   docker compose --env-file .env -f deploy/compose.yaml run --rm --no-deps gateway python -m gateway.users add --email <stage email> --role approver --kitchen all
   ```

What changes: the web needs a signed-in person; only an approver can approve, reject, make
API tokens or change settings. What does not change: the Buyer worker (its own agent token),
and outside agents on `/gateway/*` with a kitchen token. A new kitchen token must then be made
by a signed-in approver (Settings > API & MCP tokens), not by an open call to `/api`.

Off again, in under a minute: set `GATEWAY_REQUIRE_LOGIN=false` in `.env` and run the same
`up -d gateway` command. Accounts stay; the open demo is back.

### Checked end to end on 2026-11-14

Run on a laptop, not on the server: this compose file with Caddy over HTTPS (its own local
certificate), a local MongoDB with search (`mongodb/mongodb-atlas-local`), the real Valio
key and the real Buyer worker, `GATEWAY_REQUIRE_LOGIN=true`, and Chromium at 390 px.

Works:

- A visitor without a session gets the sign-in page on every screen; `/api/*` answers 401.
  A request with the old shared human token, or with a made-up `X-User`, also gets 401.
- The first sign-in with `DEMO_USER_EMAIL` and `DEMO_USER_PASSWORD` makes the approver and
  opens Home. The cookie is `HttpOnly`, `Secure`, `SameSite=Strict`, 12 hours.
- The approver asks "200 L lactose-free milk by Monday" (the Buyer worker answers: it uses
  its own agent token), sees it under To approve, approves it. The activity log and the
  order's History tab say "Order placed, By <the approver's email>".
- A chef can ask for an order (200); Approve and Reject are greyed out with "Your account
  cannot approve or reject orders."; the API answers 403 `ROLE_REQUIRED` on approve, reject
  and tokens. A viewer reads every screen; asking shows "a viewer can read, not change or
  ask" (403). No screen crashes for either.
- Sign out (in the menu at phone width) ends the session on the server. A session that
  ends while a page is open sends the person to the sign-in page at the next call.
- A wrong password says "wrong email or password". Two typos do not lock the account. Five
  wrong passwords lock it for five minutes, and the page says so.
- A token made under Settings > API & MCP tokens works on `/gateway/*` and on `/gateway/mcp`,
  and gets 403 `HUMAN_SESSION_REQUIRED` on approve, reject and making a token. The refusal is
  in the activity log. The same token on `/api/*` gets 401.
- Public with sign-in on: `/llms.txt`, `/.well-known/agent-card.json`, `/api/openapi.json`,
  `/gateway/openapi.json`, `/api/docs`, `/api/.well-known/jwks.json`, `/api/ping`.
- Off again (`GATEWAY_REQUIRE_LOGIN=false`, `up -d gateway`): only the gateway restarts,
  the open demo is back, accounts and tokens stay. On again: the same accounts work.
- The accounts command: `add` (viewer, chef, approver, `--kitchen all`), `list`; a short
  password is refused.

Not checked, or different from the server:

- Not run on the server itself, and not against Atlas: the search index was a local one.
- The accounts command was fed its password from a pipe. Typing it in a real terminal over
  SSH (the hidden prompt) was not tried.
- A proposal the Buyer worker makes says "asked by buyer-agent" in the inbox, not the person
  who typed the request. The approval names the person.
- The log names a person by email, not by display name.
- Anyone who knows an account's email can lock it for five minutes with five wrong
  passwords, again and again. Use an email for the stage account that is not on a slide.
  If it happens on stage: switch sign-in off (below), or wait five minutes.
- Change password, webhooks and the Finnish texts were not tried with sign-in on.

The morning of the demo, in this order:

1. Server: add the three lines to `.env`, run the `up -d gateway` command (steps 1 and 2).
2. Browser: open the site, sign in with the `.env` email and password (step 3).
3. Server: make the stage approver with `--kitchen all` (step 5) and one viewer for the
   judges (step 4). `python -m gateway.users list` must show both.
4. Laptop: `python -m demo.rehearsal --email <stage email>` (it asks for the password, or
   reads `REHEARSAL_PASSWORD`). All rows must be OK. With a kitchen's account instead, the
   row "Valio demand view" fails: that is the refusal from step 5, not a fault.
5. Browser, as the stage approver: Settings > API & MCP tokens, make a token with read and
   propose. Then `KITCHEN_TOKEN=<that token> python -m demo.second_agent`. `--make-token`
   does not work with sign-in on; it says so.
6. The fallback video: `DEMO_PASSWORD=<password> python -m demo.record_demo --email <stage email> --approve`.
7. Sign out, sign in as the viewer, and look at To approve: the buttons must be grey.
8. If anything is wrong: `GATEWAY_REQUIRE_LOGIN=false`, the same `up -d gateway` command,
   and run `python -m demo.rehearsal` without `--email`.

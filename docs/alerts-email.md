# Recall alerts by email, through a relay (#1187)

A kitchen webhook sends a signed `recall.alert`. A relay service checks the signature and
sends a short email. There is no email code in this repository and no new key on the server.

**Status:** the webhook side is live. `recall.alert` is sent when a recall check finds a
recalled product in stock or in recipes (case `FOUND`, #1362), once per webhook and alert.
The relay account and the webhook registration need a person: about 15 minutes.

## Rules (read first)

- **Never put an approve link in the email**, and never anything that acts by itself.
  Sign-in is off for judging, so a link that approves would approve without a sign-in. The
  email links only to the inbox page, where a person decides as usual.
- **Subscribe to `recall.alert` only.** `proposal.ready` fires on every test proposal of every
  session and uses up the relay's free limit.
- **Check the signature in the relay.** Without it, anyone who learns the relay URL can make it
  send a fake alert.
- **Keep the email short.** Product name, kitchen, what was found, and the inbox link. No prices,
  no allergen settings, no token.
- **Use a team relay account**, not a private one. **Delete the webhook after judging.**
- **Never commit the relay URL or the webhook secret.** Both are secrets.
- **Do not rehearse on `demo-kitchen`.** The recall check there is one-shot for the stage.
  Rehearse with another kitchen id, and register the `demo-kitchen` webhook only when the flow works.
- **The stage beat must not wait for the email.** Delivery takes seconds, sometimes a minute.
  The presenter names it when it arrives.

## What the gateway sends

One JSON POST per delivery (contract: docs/contract.md, "Webhooks"):

- **Headers:**
  - `X-TKB-Event`: `recall.alert`
  - `X-TKB-Delivery`: a delivery id; a repeat is a replay
  - `X-TKB-Signature`: `sha256=<hex>`, the HMAC-SHA256 of the **raw body** with the webhook secret
- **Body:** `{"id", "event", "kitchen_id", "at", "data"}`.
- **`data` for the stage case:** `case: "FOUND"`, `recall_event_id`, `product_id`, `product_name`,
  `match`, `found {stock, recipes, open_proposal}`, `notice_url`, `next_step`.
- **Retries:** at most 3 attempts within a few seconds, then the delivery is given up (it is in the
  delivery log). An alert that was not delivered is sent again at the next recall check.

## Set it up (Pipedream)

1. **Create the workflow.** In a team Pipedream account, create a workflow with an **HTTP
   trigger**. Copy its URL. Keep it out of git and chat logs.
2. **Register the webhook on the live site.**
   - Open Settings > Developer > Webhooks, add the Pipedream URL, and tick **`recall.alert` only**.
   - Copy the **secret** (`whsec_...`). It is shown once.
   - Store it in Pipedream as an environment variable, for example `TKB_SECRET`, never in the
     code step.
3. **Add a Node.js code step that checks the signature and replays:**

   ```js
   import crypto from "crypto";
   export default defineComponent({
     async run({ steps, $ }) {
       const raw = steps.trigger.event.bodyRaw;          // the exact bytes the gateway signed
       const sent = steps.trigger.event.headers["x-tkb-signature"] || "";
       const want = "sha256=" + crypto.createHmac("sha256", process.env.TKB_SECRET).update(raw).digest("hex");
       const ok = sent.length === want.length && crypto.timingSafeEqual(Buffer.from(sent), Buffer.from(want));
       if (!ok) return $.flow.exit("bad signature");
       const id = steps.trigger.event.headers["x-tkb-delivery"];
       const seen = await $.service.db.get(id);           // a replay sends nothing
       if (seen) return $.flow.exit("replay");
       await $.service.db.set(id, true);
       const body = JSON.parse(raw);
       if (body.event !== "recall.alert") return $.flow.exit("not a recall");
       if (body.data?.case !== "FOUND") return $.flow.exit("not a FOUND recall");
       const d = body.data;
       const where = [d.found?.stock ? "in stock" : null,
                      d.found?.recipes ? `in ${d.found.recipes} recipes` : null].filter(Boolean).join(" and ");
       return {
         subject: `Recall: ${d.product_name} (${body.kitchen_id})`,
         text: `Recall: ${d.product_name} is ${where || "listed"} in ${body.kitchen_id}.\n` +
               `${d.next_step}\nNotice: ${d.notice_url}\nOpen the inbox: https://kitchenbuyer.pl/approvals`,
       };
     },
   });
   ```

   The `case` check skips the older `recall.alert` for a blocked proposal
   (`case: "PROPOSAL_BLOCKED"`): its body has no `product_name`, `found` or `next_step`, so it
   would send an email that reads "Recall: undefined".

   Pipedream gives the raw body as `bodyRaw` when the trigger is set to keep the raw body;
   check that option in the trigger settings. The signature must be computed over exactly the
   bytes received, never over re-serialized JSON.
4. **Add an email step** (Pipedream's "Send Email to Self", or an SMTP step to the team's demo
   address), with the subject and text returned by step 3.
5. **Test the signature.** Press **Send test** on the webhook in Settings > Developer. A `ping`
   arrives; the code step exits with "not a recall" and sends no email. The delivery log shows 200.
6. **Test a fake request.** Send a POST with a wrong `X-TKB-Signature` to the Pipedream URL
   (for example with curl). The step must exit with "bad signature" and send no email.
7. **Rehearse on another kitchen.**
   - Register the same kind of webhook for a test kitchen and run its recall check
     (`POST /v1/kitchens/{kitchen_id}/recalls/check` with an `idempotency_key`).
   - Time how long the email takes, and write the time on #1187.
   - Only then register the `demo-kitchen` webhook for the stage.

## After judging

- Delete the webhook in Settings > Developer: this stops all email at once.
- Delete or disable the Pipedream workflow and its `TKB_SECRET`.

## Limits

- **Free plan:** Pipedream's free plan limits runs and emails a day. With `recall.alert` only,
  a demo stays far below it.
- **Delivery time** is the relay's and the mail provider's: usually seconds.
- **Retries:** if the relay is down during the gateway's 3 quick attempts, that alert is not
  emailed until the next recall check. The inbox stays the source of truth.
- **The real version** is an email channel in the gateway, with our own sending domain. That is
  not in this round.

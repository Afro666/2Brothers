# Product evidence on live proposals (#368, #376)

Optional `product_evidence` on a proposal is a list of informational records:
`product_id`, `source_url`, `checked_at`, `via`, `name`, `brand`, `pack`,
`origin`, `allergens`. Missing facts are null. `origin` is explicitly described
as bean/ingredient origin when that is what the page states. These records
never override trusted catalog allergens, supplier quotes or engine pack sizing.

Optional `label_checks` is a list with `product_id`, `label`, `producer`,
`label_verified` (`true`, `"not_found"`, or `"unknown"`), `source_url`,
`checked_at`, `scope`, `reason`, and `via`. This release supports the official
Hyvää Suomesta producer register with `scope: "producer"`; a verified producer
is explicitly described as such and is not proof of an individual SKU's
certificate or origin. Only an exact normalized legal producer name may match;
brand aliases must be supplied by the trusted catalog, never guessed by a model.

`not_found` requires an explicit complete, successful register extraction.
A partial page, missing producer, unsupported scheme, stale result or failed
fetch is `unknown`. A missing check also means unknown. Neither is verified.
UI source links use HTTPS. Evidence is recorded, dated and replayable; live
Context.dev calls require an explicit operator flag and consume credits.

`GET /v1/kitchens/{kitchen_id}/label-checks` uses the usual kitchen authorization
(`kitchen:read`). The answer is `{"checks": [...], "negative_control": {...}}`. Each
item of `checks` has the `label_checks` item shape above. `negative_control` has the
same shape plus `synthetic: true`.
Its `checks` list demonstrates the recorded producer checks for catalog products
462535, 462576 and 462775, resolved through the trusted catalog. Missing products
are omitted. `negative_control` is an explicitly synthetic unregistered producer
check, never a real product or an accusation about a supplier. Both use the dated
recording; the route does not consume Context credits. `synthetic` is true only
on that negative control. Proposal `label_checks` concern only its actual lines.

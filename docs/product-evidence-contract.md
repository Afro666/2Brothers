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

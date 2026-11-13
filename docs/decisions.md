# Decisions

One line each: `YYYY-MM-DD HH:MM – who – decision – why`.

- 2026-11-13 22:10 – Maciek (Codex), #96 – Expose only closed PolicyReason enum categories in POLICY_REJECTED feedback and audit, never values, schema paths, exception messages or upstream text – help Buyer correct read arguments without changing recovery eligibility or leaking request details.

- 2026-11-13 21:39 – Maciek (Codex), #67 – Return sanitized, audited pre-dispatch rejections of known read-only tools to the model for correction within existing budgets; mutation errors, gateway/response failures, invalid call IDs/names and audit failures still stop – recover from argument mistakes without weakening purchase or audit guards.

- 2026-11-13 21:27 – Maciek (Codex), #48 – Unknown stock remains visible for proposals but is not orderable until supplier availability is confirmed; human approval alone does not confirm stock – neither 999999 nor 9999999999 is a measured quantity, and the engine must not promise unverified fulfilment.

- 2026-11-13 – team – Work through GitHub issues and PRs, one owner per task – avoid conflicts between 3 people and 4 agents.
- 2026-11-13 20:40 – Tymon – Set up Codex CLI with Verda-hosted Kimi K3.1 Pro / DeepSeek V4.1 Flash as extra model backends (profiles `verda-kimi`, `verda-deepseek`), orchestrated by Claude – lets Claude delegate code-gen subtasks to a cheaper/faster or stronger model without building a custom server; core buyer-agent model stays Nemotron per the Verda/NVIDIA prize requirement.
- 2026-11-13 21:15 – team – Database is MongoDB Atlas (Tymon) – Atlas works, Tymon owns it; Aiven dropped.
- 2026-11-13 21:15 – Aron – Status lives on the GitHub board (users/Afro666/projects/1) – one place for 3 people and their agents.
- 2026-11-13 22:00 – team – Two-sided product: kitchen stock integration + Valio demand view from shared forecasts – Valio stand: they want to give the tool to customers and see what to buy.
- 2026-11-13 22:00 – team – Deploy the app on a Verda CPU instance, MongoDB stays on Atlas – fits the Verda track.
- 2026-11-13 23:00 – Aron – No auto-approve: the agent proposes every order, a human approves it – trust; the buyer stays in control.
- 2026-11-13 23:00 – Aron – Supplier terms (MOV, delivery fee, order days, cut-off) are user-set per supplier; demo values are placeholders – they differ per client and supplier.
- 2026-11-13 23:00 – Aron – Multi-supplier, own products, recipes, menu and week planning, future demand from the menu plan – a kitchen buys from more than Valio and plans by menu.
- 2026-11-13 23:00 – Tymon, #24 – `store/` is the one package that talks to MongoDB (sync `pymongo`); money is `Decimal` in Python and `Decimal128` in Mongo; the audit log is insert-only and hash-chained – gateway and agent import `store`, so the database can be swapped in one place and an audit entry cannot be changed unnoticed.
- 2026-11-13 23:30 – Aron – Tymon deploys the app as Docker containers on the Verda instance through GitHub Actions – he already has that pipeline.
- 2026-11-13 23:30 – Aron – The agent is called "Buyer".
- 2026-11-13 23:30 – Aron – Our own API for kitchens and suppliers (docs/contract.md, "Product API"); approve is human-only, never the agent's token – trust rule.
- 2026-11-13 23:45 – Aron – AfterQuery dropped; we stay with Valio only. `env/` stays as the synthetic history generator – one main track per project on the form.
- 2026-11-13 23:20 – Tymon, #24 – Catalog rules in `store.products.flatten`: a size read from the product name is stored but flagged `net_content_source: "name"`; the GS1 level `UNDECLARED` is its own list `allergens.undeclared` and never counts as free-from; `temperatureCondition` 5, 6 and 9 stay unknown until Valio explains them; idempotency keys are unique per kitchen – 30% of products have no measured size, and an unknown value must never look safe.
- 2026-11-13 23:32 – Tymon, #25 – Product search is one Atlas Search index `products_search` on `products` (definition in `store/search_index.json`); a misspelt allergen in `exclude_allergens` is an error, and `gluten` does not exclude oats – the free tier allows three search indexes, and silently ignoring an allergen would return unsafe products.
- 2026-11-13 23:44 – Tymon's web session, while Tymon was away, #34 – Demo consent: 16 of the 20 synthetic kitchens share their forecast with Valio (`python -m store.history --share-with valio_aimo`), every fifth is held back – the Valio demand view needs data, and the consent rule should be visible. Reversible; Tymon may change it.
- 2026-11-13 23:50 – Tymon, #163 – Own products are rows in `products` (`source: "own"`, with `kitchen_id`) in the common row shape, not a separate collection; search returns the catalog plus the asking kitchen's own products – one collection and one search index for every source (Tymon's standing decision), and a kitchen must never see another kitchen's products.
- 2026-11-13 23:58 – Tymon (relayed by his web session), #182 – A supplier sees consenting kitchens by name in the demand view, not only totals; no minimum group size; the consent text tells the kitchen so – the Valio planner needs to know whom to call, and the kitchen agrees to it when it shares. Replaces the three-kitchen floor from #159.
- 2026-11-14 00:40 – Aron – No scope freeze, but the end-to-end path comes first: real gateway (#19) and the full engine (#18), then the Valio demand view tonight (not Sat afternoon) – about 65% of the Valio score waits on a working end-to-end path; we work through the night.
- 2026-11-14 00:40 – Aron – Deferred until the end-to-end demo works: #131 settings UI, #132 learning data, #134 weather, #135 harvest calendar, #136 forecast backtest – none of them scores before the demo runs.
- 2026-11-14 00:40 – Aron – Keep the Context.dev recall monitor (#138), turn docs/scenarios.md S01–S13 into one command with a pass table, and add ElevenLabs voice approval – one small proof per side prize; robustness is 15% of the Valio score.
- 2026-11-14 00:40 – Aron – Demo: Aron presents; Tymon builds a brag repo about the project with Fable 5.2 – one voice on stage, the repo shows the work.

# Decisions

One line each: `YYYY-MM-DD HH:MM – who – decision – why`.

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

# Decisions

One line each: `YYYY-MM-DD HH:MM – who – decision – why`.

- 2026-11-13 – team – Work through GitHub issues and PRs, one owner per task – avoid conflicts between 3 people and 4 agents.
- 2026-11-13 20:40 – Tymon – Set up Codex CLI with Verda-hosted Kimi K3.1 Pro / DeepSeek V4.1 Flash as extra model backends (profiles `verda-kimi`, `verda-deepseek`), orchestrated by Claude – lets Claude delegate code-gen subtasks to a cheaper/faster or stronger model without building a custom server; core buyer-agent model stays Nemotron per the Verda/NVIDIA prize requirement.
- 2026-11-13 21:15 – team – Database is MongoDB Atlas (Tymon) – Atlas works, Tymon owns it; Aiven dropped.
- 2026-11-13 21:15 – Aron – Status lives on the GitHub board (users/Afro666/projects/1) – one place for 3 people and their agents.
- 2026-11-13 22:00 – team – Two-sided product: kitchen stock integration + Valio demand view from shared forecasts – Valio stand: they want to give the tool to customers and see what to buy.
- 2026-11-13 22:00 – team – Deploy the app on a Verda CPU instance, MongoDB stays on Atlas – fits the Verda track.
- 2026-11-13 23:30 – Aron – Tymon deploys the app as Docker containers on the Verda instance through GitHub Actions – he already has that pipeline.
- 2026-11-13 23:30 – Aron – The agent is called "Buyer".
- 2026-11-13 23:45 – Aron – AfterQuery dropped; we stay with Valio only. `env/` stays as the synthetic history generator – one main track per project on the form.
- 2026-11-13 23:30 – Aron – Our own API for kitchens and suppliers (docs/api.md); approve is human-only, never the agent's token – trust rule.

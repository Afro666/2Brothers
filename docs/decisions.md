# Decisions

One line each: `YYYY-MM-DD HH:MM – who – decision – why`.

- 2026-11-13 – team – Work through GitHub issues and PRs, one owner per task – avoid conflicts between 3 people and 4 agents.
- 2026-11-13 20:40 – Tymon – Set up Codex CLI with Verda-hosted Kimi K3.1 Pro / DeepSeek V4.1 Flash as extra model backends (profiles `verda-kimi`, `verda-deepseek`), orchestrated by Claude – lets Claude delegate code-gen subtasks to a cheaper/faster or stronger model without building a custom server; core buyer-agent model stays Nemotron per the Verda/NVIDIA prize requirement.
- 2026-11-13 21:15 – team – Database is MongoDB Atlas (Tymon) – Atlas works, Tymon owns it; Aiven dropped.
- 2026-11-13 21:15 – Aron – Status lives on the GitHub board (users/Afro666/projects/1) – one place for 3 people and their agents.

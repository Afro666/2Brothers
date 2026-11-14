# Local Codex second review without API billing

Maciek declined additional API costs and approved this alternative on 2026-11-14.
It uses the existing ChatGPT browser login and included Codex allowance. It does
not purchase credits, use an API key or claim unlimited free usage. If the signed-in
allowance is unavailable, the command stops; it never switches to API billing.

From the repository root, with `gh` and `codex` already installed and signed in:

```powershell
python .github/scripts/local_codex_review.py 1104 --repo Afro666/2Brothers --model gpt-6.1-sol --out .local/review-1104.md
```

The model name must be available to your signed-in Codex account. `gpt-6.1-sol`
was the explicit model used for the verified example on this machine. The helper:

- Refuses API-key login before starting a model request.
- Excludes OpenAI, GitHub and Verda API credentials from the child environment.
- Runs in an empty temporary directory, ignoring user provider config, with an
  explicit OpenAI provider, no command execution or web search, and a read-only sandbox.
- Supplies the bounded PR diff as untrusted data. The output names the reviewed
  commit, so a later change cannot silently turn it into a review of the latest code.
- Saves the review under `.local/` in the example; it posts nothing automatically.

Read the result, verify findings against the real implementation, and add your
triage before publishing the reviewed file:

```powershell
gh pr comment 1104 --body-file .local/review-1104.md
```

## Actual evidence

[PR #1104](https://github.com/Afro666/2Brothers/pull/1104) merged with a genuine
[local Codex review and maintainer triage](https://github.com/Afro666/2Brothers/pull/1104#issuecomment-6874140677).
The review suggested accepting missing replacement fields on extra delivery-note
lines. The current worker emits `none`, so that failure was not reproduced against
the worker. It was accepted defensively with tests; the finding was not presented
as a demonstrated production defect. A blank lot was also kept unknown.

## Hosted CI is disabled

The API workflow (`codex-review.yml`) is disabled in GitHub Actions. Its job also
requires the explicit repository variable `CODEX_API_REVIEW_ENABLED=true`; the
default is off. This guards against accidental paid calls if the workflow itself
is re-enabled. No ChatGPT authentication file is uploaded to GitHub.

The earlier API attempt authenticated but returned quota exceeded. It produced no
successful model review. The approved replacement is local development review;
**a hosted Codex CI review is not claimed**. Opus remains the required CI review.

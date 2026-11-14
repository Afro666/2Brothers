# Codex issue-to-merge recording

[Watch the 82-second recording](issue-to-merge.mp4).

This is an excerpt of actual screen captures from the #372 experiment on
2026-11-14. The dedicated windows display live CLI output, then a live
authenticated **read** of the resulting proposal and actual GitHub status for
[merged PR #1083](https://github.com/Afro666/2Brothers/pull/1083).
The recordings were cropped to their own windows, concatenated, and played at
1.25x; waiting between the verification and the merge was omitted. It is silent.
No recreated keystrokes, invented output or supplier acceptance is shown.

The proposal **write itself happened separately**, after the host reviewed the
generated client. That execution is preserved in the
[actual result](../codex-372/live-result.json), not claimed to be filmed here.
This is an operator-assisted issue-to-merge workflow, not a single autonomous
Codex action. The [full successful generation recording](../codex-372/generation.mp4)
and [all attempt timings](../codex-372/manifest.json) are also retained.

[Read verification](live-verification.json) reported `READY`, with two lines and
one unknown-stock line. The creation response reported `PENDING`; those are the
two responses at their respective times, not a claim that stock was confirmed.
The experiment invoked neither approval nor order placement.

[Verification transcript](verification-transcript.txt) records UTC times and
GitHub check states. In particular, the Codex advisory check on #1083 was skipped;
the required Opus and app CI checks passed. This video is not evidence that the
separate #361 OpenAI API reviewer had succeeded.

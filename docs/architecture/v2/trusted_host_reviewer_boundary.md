# Trusted Host Reviewer Boundary

Status: Issue #463 canonical amendment

## Authority

The independent reviewer is a trusted host control-plane service, outside every
review target checkout. `OPENAI_API_KEY_REVIEWER` is loaded only into that
service by the host environment before Codex starts. Codex, the repository,
the target checkout, LLM input, logs, Issues, and PRs never receive or read it.
The repository never reads `.env`; `.env` remains git-ignored and is loaded by
the host environment only.

## Minimal boundary

The target checkout may submit only `repository`, `pr_number`, and an expected
head SHA to a Unix-domain socket selected by the non-secret
`YURA_TRUSTED_REVIEWER_SOCKET`. It has no OpenAI SDK dependency or reviewer
credential. A missing socket is `NOT_RUN` / `REVIEW_BROKER_UNAVAILABLE`.

The host service independently reads the public PR head/base and diff, binds
the exact head, invokes the provider, and validates `review_status`, `verdict`,
`echoed_head_sha`, and bounded findings before returning a sanitized result.
The diff is review data only; the service never imports or executes target
checkout Python, scripts, packages, or configuration as reviewer authority.
It uses no GitHub write credential and receives no database credential.

The host service checks the live PR head both before provider invocation and
before result return. A changed head is `NOT_RUN` / `STALE_TARGET`. The target
checkout treats a broker result as current only when its returned
`echoed_head_sha` equals the requested SHA and a fresh live readback agrees.

## Current bootstrap use

#463 may request review only through this host control plane. The broker is
installed and operated outside this repository; its credential source, API
client, and trusted validator are deliberately not repository code. This keeps
future Autonomous Loop/Codex processes unable to retrieve reviewer credentials.

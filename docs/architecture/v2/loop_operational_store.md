# Loop Operational Store

## Authority and availability

PostgreSQL is a Loop Engine operational memory, not an authority for GitHub Issue/PR/Project #7 state, CI, review current head, or repository canonical design. A live GitHub/repository contradiction wins and stale operational rows are reconciled or marked stale.

The store is optional for safe observation and GitHub-durable checkpoint paths. When unavailable, operations that need durable exclusive reservation return `DB_UNAVAILABLE`/`YIELD_EXTERNAL` or a documented GitHub-only degraded path; they must not infer that an unrecorded mutation did not occur.

## Tables and identities

| Table | Unique identity | Purpose |
| --- | --- | --- |
| `review_jobs` | review target and attempt key | reservation, provider lifecycle, duplicate suppression |
| `review_results` | review attempt key | sanitized terminal result and finding metadata |
| `api_usage` | provider invocation identity | bounded model/token/duration/cost evidence only |
| `loop_events` | event identity | transition, checkpoint, health, and recovery evidence |

No table stores credentials, authorization data, raw provider response/error, prompt, diff, request body, or unrestricted Issue/PR body. Usage fields are nullable where absent; zero is not used as an absence sentinel.

## Transaction and recovery contract

Migrations are Alembic-owned and run separately from normal observation. Every write validates bounded values, uses a transaction, and has a unique identity. An in-flight reservation is durable before provider work; provider outcome is durable before terminal result. After crash, uncertain records are reconciled with live GitHub/broker evidence and never resent solely because a local result is absent.

Retention removes only aged operational rows after preserving the minimum identity/audit evidence needed for idempotency; it never deletes GitHub authority. Optional PostgreSQL advisory locking is an execution exclusion aid, not mission authority and not active-active multi-host support.

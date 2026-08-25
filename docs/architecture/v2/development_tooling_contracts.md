# V2 Development Tooling Contracts

Owner Issue: #353
Parent: #345
Related: #317 / #318 / #319 / #354 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

#353は、Issue graph、Architecture graph、reference analysis、ASR/video/body analysis、migration/audit等の開発支援機能をproduction Runtime Authorityから分離する。

Tooling outputは**development evidence / proposal**であり、Core StateやCharacter Definitionを自動確定しない。

---

## 2. Authority boundary

Tooling may:
- read repository/GitHub metadata through authorized adapters
- parse canonical design structure
- visualize Issue/PR/dependency relationships
- analyze reference media
- generate candidate findings/reports
- compare migration/architecture states

Tooling may not:
- mutate Core Internal State/Goal/Attention/Body/Memory
- automatically confirm Character facts
- automatically merge design conclusions into Character Bible
- act as production Input Meaning/Executive
- require production code metadata solely for visualization convenience

---

## 3. ToolingEvidenceArtifact

```text
ToolingEvidenceArtifact
- artifact_id
- tool_kind
- source_refs[]
- source_revisions[]
- generated_at
- methodology_revision
- findings[]
- limitations[]
- processing_duration_ms
- deployment_generation
- result_status
- failure_category?
```

Every finding must preserve source provenance where feasible.

`confidence`はartifact全体を確定する値ではなく、根拠ごとの
`ToolingFinding`または`ReferenceCharacterFinding`に限定する。analysis失敗は
empty findingへ縮退させず、`result_status=FAILED`とtyped `failure_category`で記録する。

Artifact is not canonical Domain State.

---

## 4. GitHub analysis boundary

GitHub tooling accesses data server-side through authenticated connector/token/CLI adapter.

Browser receives only sanitized DTOs.

Never expose:
- GitHub token
- Authorization headers
- connector credential
- private raw API response fields not needed for UI

Issue graph nodes can include safe IDs/title/status/relation metadata.

---

## 5. Issue / dependency visualizer

The visualizer is a projection of GitHub live/canonical relation data.

Requirements:
- node identity = stable Issue/PR/ref identity
- open/closed/status presentation separate from graph layout
- graph layout has no project-management Authority
- clicking node may load details via server-side API
- filters do not modify Issue state unless an explicit authorized mutation tool is invoked through separate admin flow
- edge routing/highlighting is presentation only

Layout positions must not be written into production Issue semantics unless a dedicated UI preference store exists.

---

## 6. System architecture visualizer

Input should be canonical architecture/dependency metadata derived from repository docs/manifest or explicit tooling config.

It may show:
- modules
- authorities
- ports
- data edges
- dependency levels
- implementation/verification status

It must not infer production architecture solely from directory/file names and then treat inference as canonical truth.

Inferred relationships are labelled as inferred until confirmed.

---

## 7. Character reference analysis

Reference image/video/audio analysis can produce candidate observations only.

```text
ReferenceCharacterFinding
- finding_id
- source_media_ref
- observed_feature
- evidence_interval/region
- confidence
- interpretation_notes
```

Rules:
- source observation and interpretation separate.
- one clip does not automatically become stable Character Definition.
- analysis never writes `confirmed` CharacterDefinition field itself.
- #354 Human authoring/Verification decides whether a finding enters Character Bible/YAML.

---

## 8. Media analysis

ASR/audio/body/video analysis may use external models/tools.

Keep:
- source file identity/hash where practical
- time interval
- model/tool version
- parameters relevant to reproduction
- uncertainty

Do not present model inference as direct observed fact without distinction.

Temporary media/derived artifacts follow explicit retention policy.

---

## 9. Migration / audit tooling

Audit tools may scan:
- legacy issue/requirements coverage
- forbidden imports/boundaries
- canonical link completeness
- stale branch/PR relationships
- Issue dates/project sync candidate gaps

Audit result is a report; mutations require explicit management workflow.

No script should silently close Issues/delete branches/migrate data merely because audit found a candidate.

---

## 10. Production dependency isolation

Production Core/Subsystem code must not import Development Tooling.

Allowed dependency direction:

```text
Development Tooling
→ public/read-only production contracts or repository artifacts
```

Forbidden:

```text
Core Runtime
→ development visualizer / analysis tool
```

Tooling outage never affects production runtime.

---

## 11. Render / local deployment

Tooling may run on Render or locally.

Deployment configuration may contain:
- target repo/project IDs
- service config
- auth settings

Secrets remain server-side.

A public frontend must not receive GitHub access tokens.

Health endpoint reveals only service health.

---

## 12. Untrusted data boundary

Repository content, Issue/PR text, uploaded reference files and model outputs are untrusted data.

Do not:
- execute shell from Issue text
- execute repository snippets merely to visualize them
- treat AI-generated command text as trusted
- render unsafe HTML without sanitization

File analysis adapters use bounded size/type handling.

---

## 13. Read vs mutation tools

Development tools default read-only.

If a tool later supports GitHub mutations:
- separate action/API
- explicit operator authorization
- current target/ref confirmation
- audit log
- idempotency where relevant
- no mutation from visualization click alone

Production Domain mutation remains out of scope.

---

## 14. Observability

Record:
- source refs/revisions
- analysis tool/model version
- processing duration
- failure category
- artifact ID
- deployment generation

Do not log secrets or unnecessary raw media/transcript content.

---

## 15. Required tests

- GitHub token absent from browser payload
- safe node/detail projection
- graph layout changes do not mutate Issue semantics
- inferred architecture edges clearly marked
- reference analysis produces candidate only
- CharacterDefinition not auto-updated
- source/media provenance retained
- malformed/untrusted file handling
- Tooling absent production runtime unaffected
- audit report no implicit mutation
- Render/local config secret separation

---

## 16. #445 Gate

Development Tooling implementation/extensions remain frozen until #445 D1-D9 and final user confirmation PASS.

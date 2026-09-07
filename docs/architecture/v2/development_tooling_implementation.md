# #353 Development Tooling 実装整合

対象Issue: #353

この文書は `development_tooling_contracts.md` を置換しない。#353の実装がcanonicalの読み取り専用境界をどのように満たすかを示す。

## 実装配置

- `tools/development_tooling/contracts.py`: immutable evidence、Issue/Architecture graph、reference finding、server/browser config
- `tools/development_tooling/service.py`: safe GitHub projection、Architecture projection、reference candidate projection、read-only audit
- `tools/development_tooling/untrusted.py`: bounded JSON object解析

production `app/**` はこのpackageをimportしない。

## canonical対応

| canonical節 | 実装対応 |
| --- | --- |
| 3 | `ToolingEvidenceArtifact`、`ToolingFinding`、`SourceReference`がartifact・methodology・source revisionを保持する。 |
| 4–5 | `GitHubIssueProjector`はallowlist済み入力だけを受け、browserにはsafe Issue graph DTOのみを返す。layoutやclickはmutation APIを持たない。 |
| 6 | `ArchitectureEdgeEvidence`でcanonical、explicit tooling config、inferredを区別し、inferred edgeを明示する。 |
| 7–8 | `ReferenceCharacterFinding`はobservation/interpretationを分離したcandidate-only evidenceであり、`INTERPRETATION`はnon-empty notesを必須とし、`OBSERVATION`はnotesを持たない。`MediaAnalysisProvenance`がtool revision・再現に必要なsafe parameter・retention policyを保持する。Character Definitionは更新しない。 |
| 9 | `DevelopmentAuditService`はevidence artifactだけを返し、processing duration、deployment generation、result status、typed failure categoryを欠損なく伝播する。Issue close・branch削除・data migrationの操作を持たない。 |
| 10–13 | `ToolingServerConfig`はsecretをserver側へ閉じ、browser configへ投影しない。untrusted inputはbounded JSON dataとしてのみ扱い、decode段階の再帰失敗も`ValueError`へ正規化する。 |
| 14–15 | artifactにsource/methodology/generated time/limitationを保存し、required boundaryをdirect testで検証する。 |

外部GitHub/media adapterおよびUIは、この最小read-only contractの外側で明示的に接続する。adapterが変更操作を追加する場合は、canonical §13の別action・operator authorization・target confirmation・audit logを持つ別Workで扱う。

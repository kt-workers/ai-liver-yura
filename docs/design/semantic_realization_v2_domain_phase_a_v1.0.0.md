# Semantic Realization v2 Domain Phase A v1.0.0

## Status

- Parent: #225
- Work: #303
- Design gate: PR #302 / `semantic_realization_validation_reassessment_v1.1.0.md`
- Phase: A — Domain / compatibility
- Date: 2026-08-12

本書は、Semantic Realization v2の最初のProduct実装として、直交化したSemantic DomainとLegacy `state` Adapterを既存production経路へ影響させず導入するための実装契約を固定する。

## 1. Phase Aの目的

Phase Aでは次だけを実装する。

1. `SemanticValue`
2. `SemanticPropositionV2`
3. `SemanticUtterancePlanV2`
4. `LegacySemanticStateAdapter`
5. Legacy `SemanticUtterancePlan` → v2変換
6. v2 context serialization / conservative parsing
7. Domain unit tests

Phase AではCharacter / Verifier / OpenAI Adapter / Runtime acceptance経路を切り替えない。

## 2. 加算導入を選ぶ理由

現行`SemanticProposition.state`は#226/#227/#229 stackのproduction contractとして既に広く参照されている。

Phase Aで既存classのfieldを直接置換すると、Domain migrationとCharacter/Validator migrationが同じ差分へ混在し、failure原因を切り分けにくい。

そのためPhase Aでは新しいv2型を別moduleへ加算する。

```text
existing production
SemanticUtterancePlan / SemanticProposition(state)
        │
        ├── unchanged in Phase A
        │
        └── LegacySemanticStateAdapter
                  ↓
          SemanticUtterancePlanV2
```

Phase B/Cでv2 consumerが完成した時点でproduction routingをv2へ切り替える。

## 3. module boundary

新規module:

```text
app/domain/semantic_utterance_v2.py
```

既存`app/domain/semantic_utterance.py`はPhase Aでは変更しない。

v2 moduleは既存型のうち意味が変わらない以下を再利用できる。

- `SemanticTarget`
- `InterpersonalContentContext`
- `SemanticUtterancePlan`（Legacy入力型としてのみ）

## 4. SemanticValue invariant

```python
SemanticValue(
    status="known" | "unknown",
    polarity="present" | "absent" | None,
    degree="low" | "moderate" | "high" | "very_high" | None,
    certainty="low" | "medium" | "high",
)
```

### unknown

```text
status == unknown
→ polarity is None
→ degree is None
```

### absent

```text
status == known
polarity == absent
→ degree is None
```

### degree

```text
degree != None
→ status == known
→ polarity == present
```

### ordinary detail presence

```text
status == known
summary_mode == detail
→ polarity must be present or absent
```

`certainty`はvalue availabilityとは独立したepistemic commitmentである。

## 5. SemanticPropositionV2

```python
SemanticPropositionV2(
    proposition_id: str,
    kind: str,
    predicate: str,
    value: SemanticValue,
    concept: str | None,
    summary_mode: "detail" | "overview",
    realization_policy: "required" | "optional",
    evidence_refs: tuple[str, ...],
)
```

### overview invariant

```text
summary_mode == overview
→ value.status == known
→ value.polarity is None
→ value.degree is None
```

### detail invariant

```text
summary_mode == detail
value.status == known
→ value.polarity != None
```

### identity

`proposition_id`はPlan内で一意でなければならない。

Phase AのLegacy migrationでは:

```text
proposition:{index}:{predicate}
```

を生成する。

### realization policy

Legacy migrationでは:

```text
index == 0 → required
index > 0  → optional
```

とする。この暗黙規則はAdapterにのみ存在し、v2 Domain consumerは`realization_policy` fieldを参照する。

## 6. LegacySemanticStateAdapter

Legacy `state`の意味変換は1か所に固定する。

| Legacy state | status | polarity | degree | summary_mode |
|---|---|---|---|---|
| absent | known | absent | null | detail |
| present | known | present | null | detail |
| low | known | present | low | detail |
| moderate | known | present | moderate | detail |
| high | known | present | high | detail |
| very_high | known | present | very_high | detail |
| unknown | unknown | null | null | detail |
| overview | known | null | null | overview |

Adapterは未知のLegacy stateを`unknown`へ黙って補正しない。不正値は`ValueError`とする。

逆変換も上表に一致するvalid v2 combinationだけをLegacy stateへ戻せる。

## 7. SemanticUtterancePlanV2

Plan v2は既存Planの非proposition fieldを維持する。

- speech_act
- target
- required_content
- optional_content
- forbidden_additions
- response_length
- self_disclosure
- question_budget
- new_direction_budget
- interpersonal
- discourse_context
- reasons

propositionsだけを`SemanticPropositionV2`へ置換する。

Plan内の`proposition_id`重複はfail closedする。

## 8. Context contract

v2 `as_context()`はLegacy `state`を出力しない。

```json
{
  "proposition_id": "proposition:0:joy",
  "kind": "internal_state",
  "predicate": "joy",
  "value": {
    "status": "known",
    "polarity": "present",
    "degree": "high",
    "certainty": "high"
  },
  "concept": null,
  "summary_mode": "detail",
  "realization_policy": "required",
  "evidence_refs": []
}
```

v2 `from_context()`はcanonical v2 shapeだけを読む。

- required field欠落
- enum不正
- cross-facet invariant違反
- duplicate proposition_id

を意味値へ補完せず、Plan全体を`None`としてfail closedする。

Legacy raw dictをv2へ直接曖昧変換しない。Legacy contextは一度既存`SemanticUtterancePlan.from_context()`境界を通したtyped objectから`from_legacy()`で移行する。

## 9. Production routing

Phase A完了時点ではproduction routingを変更しない。

```text
ResponseSemanticsPlanner
→ Legacy SemanticUtterancePlan
→ current #227/#229 path
```

v2はUnit / Adjacent準備用のDomainとして存在する。

Phase B/CでStructured Character / Semantic Verifierがv2を受け取れる状態になってから切り替える。

## 10. Rollback

Phase Aは新規module + testsのみなので、rollbackはv2 module参照を削除するだけで既存productionへ戻れる。

Legacy `state`の意味判定をfinite自然語辞書へ接続しない。

## 11. Automated Gate

最低限以下を固定する。

- Legacy 8 statesがexactにv2へ写像される
- v2→Legacy round-tripが8 statesで一致する
- unknown / absent / degree / overview invariant違反をreject
- known detailでpolarity欠落をreject
- Legacy Planからstable proposition_idを生成
- first required / supporting optionalをAdapter内だけで付与
- Plan内duplicate proposition_idをreject
- `as_context()`にLegacy `state`が存在しない
- canonical v2 context round-trip
- invalid v2 contextは補完せずfail closed

## 12. Phase A完了条件

- [x] v2 Domain実装
- [x] Legacy Adapter実装
- [x] Unit tests PASS
- [x] existing production path未変更を差分監査
- [x] Full regressionで既存契約へのデグレがないことを確認

## 13. Verification evidence

2026-08-12に以下を確認した。

- Implementation PR: #306（Draft / stacked）
- CI-only PR: #307（`feature/core-development` base、マージ禁止）
- GitHub Actions: run #1266 / run id `31587316526`
- `tests` job: SUCCESS
- completed: `2026-08-12T10:34:58Z`

差分監査ではPhase AのProduct変更は新規`app/domain/semantic_utterance_v2.py`への加算導入に限定され、既存`app/domain/semantic_utterance.py`、Character、Verifier、OpenAI Adapter、Runtime acceptance routingは変更していない。

したがってPhase Aは完了とし、#303 Implementation Gateの`v2 Semantic Domain / Legacy Adapter`を完了扱いにしてPhase Bへ進む。

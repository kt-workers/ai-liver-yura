# Semantic Verification D10 Bounds — Issue #363

Owner: #363
Shared canonical: `brain_operational_bounds_contracts.md`

## Capacity authority

`BrainOperationalBoundsPolicy.semantic_verification` を唯一の容量Authorityとする。

- blind units: 128
- evidence refs per blind unit: 16
- evidence quote: 512 Unicode code points
- interaction acts per blind unit: 4
- supporting blind units per proposition relation: 32
- proposition relations: 64
- blind unit accounting entries: 128

既存DTO内の独立上限（blind units 64、quote 1000）はproduction Authorityとして使用せず、共有Policy Gateへ移す。

## Role A boundary

Role A Provider candidateは、全material semantic contentをbounded observationとして表現できる場合だけcommit可能とする。

- units > max_blind_units は `SEMANTIC_OBSERVATION_TOO_LARGE`
- unit evidence > max_evidence_refs_per_unit は同じくfail-closed
- interaction acts > max_interaction_acts_per_unit はfail-closed
- evidence quote > max_quote_codepoints はsubstring短縮せずfail-closed
- 129 unitsを先頭128としてacceptしない

Overflow時はBlindUtteranceObservationを成功扱いせず、最終SemanticAcceptanceも生成しない。

## Role B boundary

Role BはPlan proposition全件とRole A blind unit全件をaccountする。

- proposition observations > max_proposition_relations はfail-closed
- blind unit accounting > max_accounting_entries はfail-closed
- supporting blind units per proposition > max_supporting_units_per_proposition はfail-closed
- Role B内のevidence quoteもmax_quote_codepointsを超えられない

件数都合でPlan proposition observation又はblind unit accountingを削除してsuccessにしない。既存Authorityのexact accounting/grounding Gateを維持する。

## Policy freshness

Role A / Role B requestは同一 `BrainOperationalBoundsPolicy.policy_id / policy_revision` generationへbindする。

- Role A await中のgeneration変更はblind commit前にstale reject
- Role A commit後、Role B request前にgenerationが変わった場合はRole Bを開始せずstale reject
- Role B await中のgeneration変更はrelation commit / reconcile前にstale reject
- old resultをnew generationへ付け替えない

## Preserved authority

この補完では以下を変更しない。

- Role A plan-blind topology
- Role B exact Plan proposition / blind unit accounting
- evidence actual utterance grounding
- polarity/certainty/degree/execution truth reconciliation
- closed SemanticAcceptance policy
- #348 repair orchestration
- #330 Character generation Authority

## Required tests

- blind units 128/129
- evidence refs 16/17
- quote 512/513 Unicode code points、multibyte byte数と区別
- interaction act policy equal/above（closed enumで到達可能なcustom boundを使用）
- supporting units 32/33
- proposition relations 64/65
- accounting entries 128/129
- oversized Role A / B Provider resultをfirst-N acceptしない
- overflow時にAcceptanceが生成されない
- Role A / Role B await中のpolicy generation変更をstale reject
- existing exact accounting / evidence grounding / acceptance regression

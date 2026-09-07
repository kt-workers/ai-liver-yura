# Character Language D10 Bounds — Issue #330

Owner: #330
Shared canonical: `brain_operational_bounds_contracts.md`

## Capacity authority

`BrainOperationalBoundsPolicy.character_language` を唯一の容量Authorityとする。

- constraint views: 128
- confirmed profile facets: 128
- segments: 64
- segment text: 2048 Unicode code points
- total utterance text: 8192 Unicode code points
- realization refs per segment: 32

## Input boundary

Planが要求するrelationship/discourse constraintは全件exact groundingを維持する。128件を超える場合は選別せず `CHARACTER_CONTEXT_TOO_LARGE` とする。

CONFIRMED profile facetが128件を超える場合、#330は先頭N件を選ばない。Profile ownerで明示的にbounded化されていない入力として `CHARACTER_CONTEXT_TOO_LARGE` とする。ProfileやSnapshot自体は変更しない。

#362のquestion/new-direction budgetはそのまま搬送し、#330固有の意味上限として再定義しない。

## Output boundary

Provider candidateとcommit対象candidateへ同じGateを適用する。

- segments <= 64
- each segment text <= 2048 code points
- total text <= 8192 code points
- realization refs per segment <= 32

超過は `CHARACTER_OUTPUT_TOO_LARGE`。substring短縮、segment削除、realization ref削除、先頭N件受理は禁止する。

## Policy freshness

async requestは使用した共有Policyの `policy_id / policy_revision` generationへbindする。Provider待機中にgenerationが変わった結果はnew boundsへ付け替えずstale rejectする。

## Preserved authority

既存の#362 What-to-say、REQUIRED/FORBIDDEN grounding、Plan budget、#355 Profile、Profile/constraint live stale、#363 semantic acceptance、#331/#348 runtime境界は変更しない。

## Required tests

128/129 constraint、128/129 confirmed facets、64/65 segments、2048/2049 segment codepoints、8192/8193 total codepoints、32/33 realization refs、multibyte Unicode、oversized Provider result no truncation、late policy generation stale、既存回帰を検証する。

# V2 Input Meaning実装契約

Status: Issue #326 implementation canonical
Parent: `brain_architecture.md`
Input: `input_gateway_contracts.md`
LLM: `llm_role_contracts.md`

## 1. 責務

Input MeaningはText/STTの自然言語を`StructuredInputMeaning`へ変換する唯一のopen-ended semantic authorityである。Appraisal、Goal、Attention、返答内容、Activity実行を決定しない。下流はraw textを再解釈しない。

## 2. 入出力

入力は#349の`NormalizedInputEvent`とbounded `ReferenceContext`。Text/Speech以外、lifecycle、空の`text`、schema不一致をfail-closedで拒否する。TextとSTT transcriptは同じRoleとschemaを使う。

出力はimmutableな`StructuredInputMeaning`であり、speech act、primary intent、expected response、target、entities、references、provided information、negation、hypothetical、temporal relation、confidence、unresolved fieldsを持つ。confirmation、Activity start/stop、internal-state questionはprimary intentのtyped値として表す。

## 3. ReferenceContext

`ReferenceContext`はrevision付きbounded snapshotで、recent speech/presentation、Executive decision、Goal/Commitment、Activity/Actual Fact、current topic、Memory evidenceへのtyped referenceを保持する。上限超過、重複ID、future revisionを拒否する。LLMがreferenceを解決できなければ`unresolved_fields`へ残し、clarificationへ閉じる。

## 4. LLM境界

Input Meaning Roleは#323の可変Role契約を使う。requestはsource event/context revision、foreground priority、cancellation、stale policyを運ぶ。Provider名や固定Role番号を持たない。Provider resultはexchange identity/schema/revision/timestampを検証後、Input Meaning所有validatorが厳密なoutput schemaを構築する。

## 5. commit policy

次は`clarification_required`とする。

- confidenceがpolicy threshold未満
- target/reference等の必須解決項目が未解決
- Roleが明示的にclarificationを要求

current context revisionとrequest revisionが異なるresult、非success、schema/identity違反はcommitしない。`mark_stale`や`revalidate`であっても本Issueのcommit関数は最新revisionの明示一致を要求する。

## 6. 禁止事項

- keyword、正規表現、substring、固定phrase辞書をsemantic authorityにすること
- raw textを`StructuredInputMeaning`へ残し、下流に再解釈させること
- Vision/Touch/Game等を自然言語へ強制変換すること
- Input MeaningがAppraisal、Internal State、Goal、Attention、Execution Factを変更すること
- LLM自由文やProvider objectをDomain出力にすること

## 7. 並行性

Role Portの1 requestだけをawaitし、global lockや直列queueを所有しない。Runtime priority/backpressureは#322が所有する。slow Input Meaningがunrelated laneを停止しないことはFake Portを用いた隣接testで確認する。

## 8. 受入条件

- 全公開snapshotがstrict JSON serializableかつimmutable
- Text/STTが同一semantic authorityを通る
- paraphraseはProvider出力に基づき同一typed meaningとして受理できる
- missing target、general reference、negation、hypotheticalを構造化できる
- low confidence/unresolvedをclarificationへfail-closedにする
- stale、schema違反、非言語eventをcommitしない
- runtime codeにfinite surface matcherを置かない
- Provider SDK import、Appraisal/Goal/Attention判断を持たない

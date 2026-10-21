# 内部状態の時間関数・Executive投影・保存復元契約

状態: 正本補足（設計のみ）。上位: [自律人格と統合本体](autonomous_character_contracts.md)。
既存契約: [Appraisal/Internal State](appraisal_internal_state_contracts.md)、[Decay Numerical](appraisal_decay_numeric_contracts.md)、[Executive](executive_authority_contracts.md)、[Persistence](persistence_repository_contracts.md)。
採用言語環境: Python 3.10.5。製品コード/試験への反映および実動作は未完了。

## 1. 基本原則・正本の区別

- 内部状態は数値を廃止するのではなく、**Reducerが確定した有限数値・原因・世代をアンカーとして、採用済みの時間関数を時刻指定で評価できる状態**とする。投影した値のみを「心理状態の全体」とみなさない。
- 既存9系統のfacet identity、`InternalStateSnapshot`、`InternalStateReducer`、`AppraisalCandidate`、`StateDeltaProposal`、stale/currentness規則を維持する。
- **確定状態**と**関数を読んで得た時点別投影**を別型・別Authorityとして扱う。投影のreadは状態更新、Goal、発話決定、実測事実ではない。
- LLMや記憶やBodyが確定状態を直接書かない。発話/沈黙はExecutiveの選択であり、値の閾値判定を新設しない。
- 任意のPython関数オブジェクト、LLM生成コード、eval、pickleを状態の保存形式にしない。関数種別・policy identity/revisionと検証済みパラメータを宣言的に保存する。

## 2. 型付き状態と時間投影の論理モデル

以下は新たに導入すべき**論理契約名**であり、現在のPythonに実装済みという意味ではない。

```text
StateTrajectoryAnchor
- facet_ref                         # 既存kind/key/target_ref
- committed_value                   # Reducerが確定した値 [-1,1]
- committed_at                      # timezone-aware絶対時刻
- state_revision
- source_context_revision
- confidence                        # [0,1]
- cause_refs[]
- evolution_policy_id/revision

TemporalFacetProjection
- facet_ref
- as_of                              # 1 request中共通の評価時刻
- anchor_identity
- projected_value?                   # [-1,1]; 評価不可ならなし
- evolution: DECAYED | HELD_NO_RULE | NOT_EVALUABLE
- delta_since_anchor?                # 算出根拠があるときのみ
- supported_trend?                   # 履歴・方針から示せる変化
- cause_refs[] / evidence_refs[]
- evolution_policy_id/revision

InternalStateTemporalView
- source_state_revision
- source_context_revision
- as_of
- projections[]
- supported_baseline_differences[]   # 根拠ある個体基準に限る
- evidence_refs[]
- view_identity
```

- 既存の`InternalStateFacet.current/previous/last_delta/confidence/causes/updated_at`は確定値のまま保持する。新たな投影でその値を上書きしない。
- facetsが未登録なら0へ補完せず未観測として扱う。過去感情記憶やCharacter静的Traitから新しい現在facetを捏造しない。
- view全体を同じstate revision、source context revision、関数policy generation、`as_of`に束縛し、部分取得値を異なる世代から寄せ集めない。
- 現在値、直近の確定delta、原因、時間的推移、通常との差をそれぞれ別項目とする。未確定の基準や不連続点の導関数を作らない。

## 3. 時間関数の評価と数値規則

```text
read_at(as_of, committed_snapshot, active_evolution_policy)
    -> InternalStateTemporalView
```

1. `as_of`は呼出し側がRuntimeClockから取得し、timezone-aware値として明示注入する。Domain内で壁時計やLLMを呼ばない。アンカー以前や未観測の未来の出来事を外挿しない。
2. 最新の確定facet値をanchorとする。適合するVersioned Decay ruleを、既存のexact facet kind/key/target scopeの優先順位で決定する。
3. ruleがあり必要経過時間を満たす場合、既存の正本指数式だけを使用する。
4. ruleがなくてもデータを勝手に変化させない。既存の`DECAY_POLICY_RULE_MISSING` diagnosticを保持し、`HELD_NO_RULE`は「最後の確定値を提示、自然変化は未定義」の意味とする。Policy全体の欠落・不正は評価失敗とし、`HELD_NO_RULE`で隠さない。
5. 最小経過時間未満はアンカー値の投影のみであり、正規Decay proposalは生成しない。評価で得た値を黙ってclampしない。
6. 同じanchor、policy generation、時刻なら同じ結果を返す。評価不能・非法値・世代不整合は型付き失敗であり、暗黙の別公式による修復を行わない。

既存の関数式は次を**そのまま継承する**。

```text
elapsed_seconds = max(0, as_of - anchor.committed_at)
factor = 2 ** (-elapsed_seconds / rule.half_life_seconds)
projected_value = rule.neutral_baseline
                  + (anchor.committed_value - rule.neutral_baseline) * factor
```

採用済み初期規則は Emotion(global/targeted)半減期300秒、Arousal(global/targeted)半減期120秒、baseline=0、minimum elapsed=1秒。これらは[本番構成](appraisal_production_configuration.md)における初期**校正値**であり、人間心理の実測最適値と主張しない。

Desire、Drive、Motivation、Value、Interest、Relationship、Energyには本番初期方針の自動Decay ruleが**ない**。そこへ減衰や回復の式を推測で追加しない。人格Traitを値へ一対一変換しない。

## 4. Appraisal→Reducerの書込み・二重減衰防止

```text
信頼済みEvent/Meaning/Memory等
 → AppraisalCandidate / StateDeltaProposal
 → ownerがcurrent snapshotとpolicy generationを確認
 → Decay確定が必要なら既存Decay ProposalをReducerへcommit
 → 新しい確定snapshotを基準にAppraisal候補を再構築/現在性検証
 → Reducerが唯一の短い原子的commitを行う
 → state revisionを進め、新しいanchorとして公開
 → 時刻指定read view、Attention/Executive/Bodyへ由来付きで投影
```

- 読み取っただけでは`InternalStateSnapshot.revision`を増やさない。減衰を先に正規commitした場合は、新しいanchorから将来分を評価する。同じ経過秒を二重に減衰しない。
- Appraisalの旧候補を新しいanchorへ付け替えず、元revision mismatchならstale reject。必要なら新requestを開始する。古い結果を最新状態へ暗黙mergeしない。
- Decay/Presentation/Executiveの独立した非同期処理はDomain lockを待ち続けない。Reducer lockは短いatomic mutationのみを保護し、LLM/DB/外部callbackを内包しない。
- この調停フローは**新しい設計要求**であり、現在のReducerが時点別投影を自動適用しているという意味ではない。

## 5. Executive LLMへの入力・判断

既存の`ExecutiveContextSnapshot.internal_state`は確定`InternalStateSnapshot`のままとし、隣接する**新しい型付き項目**`internal_state_temporal`を設ける。既存の`executive.context.v2`へ無断で追加せず、次の互換でない明示schema世代（例: v3）を所有者の設計/実装で定義してから、serializer/parser/Role instructionsを一致させる。例の世代番号はこの設計で実際に登録されたとはみなさない。

LLMには、確定値と投影値の区別、同じ評価時刻、直近の確定状態変化、増加/減少/維持の根拠、原因参照、policy世代、必要なMemory/Goal/Attention/Situationを渡す。根拠ある個体基準だけを相対差として提供する。単なる`0.7`を「喜びが強い」と固定翻訳しない。

- Executiveは`respond / act / wait / ignore / continue_activity / defer / refuse / silence`を自律的に選ぶ。数値・変化率による固定閾値の発話ルールは設けない。
- Executiveに渡すのは関数**のコード**ではなく、検証可能な型付きの状態投影と出典。新しい「時間の状態解釈LLM」を必須段としない。
- LLM完了後は既存4-revision stamp（source/goal/attention/internal state）に加えて、使用した関数policy generationと必要な状態viewの現在性を検査する。LLM待機中に状態更新や関数方針変更があれば、旧判断を確定しない。
- **時間経過だけ**で全LLMが毎瞬間staleになる扱いはしない。時刻の有効性・重要変化の再評価範囲はOwnerの明示policyが必要であり、未確定の秒数や閾値を導入しない。
- Snapshotは既存のBrain共通bounded context制約を用いる。必要な根拠を切り捨てて「正常」へ変換しない。容量不足は型付き失敗。
- Speech Semanticsは上流で確定した意図と正規Factを使用する。Character Language LLMは生のEmotion/Desire/Drive値、関数、raw historyを再解釈しない。人物らしい表現は確定した意味とCharacter Profile/表現制約を受け取る。

## 6. Restart-safe保存・復元

現行[Persistence](persistence_repository_contracts.md)§5でEmotion等の現在snapshotは**restart-safeとして承認されていない**。本設計はその禁止を自動解除しない。

新しいOwner固有の保存候補（未実装）は以下。

```text
InternalStateTrajectorySnapshot
- snapshot_schema_id/version
- owner_identity / state_revision / source_context_revision
- captured_at / runtime_epoch
- canonical_committed_anchors[]
- evolution_policy_identity/revision
- bounded_committed_change_provenance[]
- integrity digest / relevant source references
- restore_policy: historical_only | validated_restart_safe
```

- 保存Adapterは既存`PersistenceSnapshotEnvelope`のpayload/digest、version、epoch、complete transactionを検証する。任意Python object、pickle、実行関数を復元しない。
- Internal State Ownerがrestore可否、時刻、anchor・state revision、policy世代、因果出典、schemaと完全性を再検査し、**明示承認された場合のみ**新runtime epochに採用する。Persistence Adapterは独自に`set_state`しない。
- 停止中の時間は採用済みDecay policyによる評価候補として扱い、過去の状態を現在の値へ無条件コピーしない。
- 復元契約未承認・旧版不整合・破損は現在値として採用不可。明示的な新規起動は空facet/revision0の初期化規則を使用し、復元失敗の要求を黙って新規起動成功に置き換えない。
- DB不在・復元失敗後の暫定運転は非永続・degradedであることを示し、DB復旧時の古い保存データと暫定現在状態を無許可で合体/上書きしない。
- Character Definitionの世代変更をまたぐ基準値やanchorの意味は明示migration契約がある場合だけ継続する。通常状態のbaselineをDecoderが推定しない。
- 保存頻度・圧縮方針・保持容量は未確定。出典と信頼性を消す無制限の圧縮も、無制限の履歴保存も採用しない。

## 7. 受入観点（旧方式との比較なし）

1. 同じanchor/policy/as_ofの値とtrendは同一で、Python 3.10.5上で検証可能。
2. 既存Decay式・優先順位・対象scope・最小経過時間・値域・Policy currentnessを維持。
3. ruleなしでは値を勝手に減衰させず、欠落facetを0で補わず、Policy不正を隠さない。
4. readで確定状態・revisionを変えず、DecayとAppraisalの連続更新で二重減衰しない。
5. state/context/policy変更中の遅いLLMの旧候補を拒否し、時間経過だけの無制限な全失効を生まない。
6. Executiveが時間の根拠を含むviewを受け取り、発話/沈黙をLLMで選ぶ。固定発話閾値なし。
7. Character Languageへraw数値や関数コードが漏れず、意味保持と自然さのOwner境界が成立。
8. 長いTTS/DB/Body中も状態readと認知判断が非直列で継続。
9. 保存版・時刻・policy・digest不一致は復元失敗。認可前の現在状態復元は行わない。
10. 新旧方式のA/B比較・改善率測定は受入に不要。総pytestケース数1,000以内で他の必須受入を維持。

## 8. 未確定値と実装への接続

本契約は**関数評価の正本構造**を定めるが、次を架空の値で埋めない。

- 未定義facetの自然変化・回復・相互作用に関する数式。
- 個体baselineの観測窓・品質・適用基準。
- 投影viewに固有の容量、秒数による意味失効、履歴圧縮・保存頻度。
- Owner固有のrestart-safe current stateを正式承認するための移行条件。

実装着手時は、Appraisalの正規状態更新Owner、Executiveの入力schema/port/fence、PersistenceのDomain-owned再構築、Speech/Characterの権限をそれぞれ個別に改修する。現在のソースがこの契約を満たしたという記述ではない。

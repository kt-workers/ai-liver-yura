# AI Liver ゆら V2 Legacy Migration Matrix

Status: Draft / V2 Design Gate / Cognitive-LLM reconciliation 2026-08-12
Root: #317
Management work: #318
V2 branch: `rebuild/v2-foundation`

Canonical designs:
- `docs/architecture/v2/system_architecture.md`
- `docs/architecture/v2/brain_architecture.md`
- `docs/architecture/v2/cognitive_llm_architecture.md`
- `docs/architecture/v2/concurrency_architecture.md`
- `docs/architecture/v2/speech_pipeline_architecture.md`
- `docs/architecture/v2/body_architecture.md`
- `docs/architecture/v2/plugin_architecture.md`
- `docs/architecture/v2/subsystem_architecture.md`

## 1. 目的

この文書は、V2再構築で旧Issue / PR / design generationを捨てる前に、**重要な要求・不変条件・失敗知見・Verification条件をV2へ回収したことを証明する移行台帳**である。

V2は最古`main@0500a69c75e46e97c0f849c26a4d3d7f1fb138dd`から再構築する。旧コードをV2へmerge / cherry-pickして継承しない。

```text
Legacy Issue / PR / design / verification history
        ↓
retain requirement / invariant / failure class / test case
        ↓
V2 canonical design + V2 Issue
        ↓
new implementation from the oldest-main V2 lineage
```

### 2026-08-12 Cognitive / LLM再設計で確定した移行原則

V1で得た責務分離は維持するが、以下の旧V2前提は撤回する。

- システム全体でLLM Roleを4個に固定する
- 第5 LLM責務を禁止する
- Commanderが`What to say`まで詳細確定する
- 責務分離されたLLMを毎回直列awaitする

新しい原則:

- LLM Role数は独立責務から決まり、固定しない
- `Logical Role数 != API call数`
- ゆらの意識的Goal / Action selectionの最終AuthorityはExecutive Deliberator #328だけ
- What to sayはSpeech Semantics #362、How to say itはCharacter Language #330
- Character発話の独立意味観測はSemantic Verification #363
- Memoryのopen-ended consolidationはReflection #364、保存・想起はMemory Store #332
- complex Goalの実行分解はGoal Planning #361
- Gameのframe-level技能はGame Skill #365でCore Executive latencyから分離
- RuntimeはEvent-driven / snapshot-based / sparse activation / concurrent lanesを採用する

---

# 2. Authority snapshot

初回inventory（2026-08-12 GitHub live確認時点）:

- Legacy Open Issues: **44**
- Open PRs: **23**
- 初回V2 Issue体系: #317〜#360
- Cognitive/LLM再設計で追加: #361〜#365
- V2 canonical branch: `rebuild/v2-foundation`

初回Open PR 23本はGitHub live `is:pr is:open`検索で全件確認した。

旧Issue/PRをcloseするのは、本MatrixでV2移行先と残す要求を確定した後とする。

---

# 3. Disposition

| 区分 | 意味 |
|---|---|
| `MIGRATE` | 要求・知見をV2へ移し、旧実装lineageはV2へmergeしない |
| `OPS-RETAIN` | V2にも継続適用する運用正本。単純supersedeしない |
| `HISTORY-RETAIN` | 開発経緯資料として保存するがproduct authorityにはしない |
| `TOOLING-MIGRATE` | 本番RuntimeではなくV2 Development/Validation Toolingへ再配置 |
| `CI-ARCHIVE` | 一時CI用途。検証知見だけ回収し実装を移さない |

---

# 4. Legacy Open Issue migration

| Legacy | 残す要求・知見 | V2 destination | Disposition |
|---|---|---|---|
| #186 起動時の覚醒反応 | 固定neutral/固定挨拶にせず、前回状態・停止時間・現在状態からAppraisalしSpeech/Body/Silenceへ因果接続 | #327 #333 #337 #350 #359 #360 | MIGRATE |
| #187 GUI全画面最新化 | `gui/*`棚卸し、public DTO/read model、接続/切断/再接続、Render/ローカル、実画面Verification | #351 | MIGRATE |
| #189 会話生成・発話準備の因果状態 | 生成中も無反応にせずturn/process factsとExpression/Discourseを因果接続。固定「考え中Motion」で隠さない | #327 #333 #337 #348 #362 #330 #334 | MIGRATE |
| #190 InteractionProcessSnapshot | 入力受理・生成・検証・Text/TTS/presentation・turn・cancel等の実行事実を型付きrevisionで観測 | #321 #322 #333 #348 | MIGRATE |
| #191 Interaction Process Appraisal | 実行事実をattention/uncertainty/commitment/readiness等へ評価し、処理段階→固定Motionにしない | #327 #333 #337 | MIGRATE |
| #192 Expression Appraisal | Emotion/Motivation/Interaction状態をBody/Voice/Silence向け高レベル表現へ統合し固定関節動作へ直結しない | #337 #331 | MIGRATE |
| #193 Discourse Appraisal | topic distance、bridge、acknowledgement、response obligation等をtypedに評価し固定Prefixを使わない | #327 #362 | MIGRATE |
| #194 Turn-taking最終統合 | 通常/自律/中断/TTS failure/長い生成待ちを統合し発話前後因果・turn返却をSystem確認 | #333 #334 #348 #360 | MIGRATE |
| #195 旧実行ロードマップ | 旧順序を正本にせず、依存・Start/Target・Verification管理だけ維持 | #317 #319 | MIGRATE |
| #196 Awakening Context/Persistence | cold/restart/resume、停止時間、必要最小snapshot、DB unavailableでも起動 | #327 #350 #359 | MIGRATE |
| #197 Awakening Appraisal/Lifecycle | 起動ContextをEmotion/Desire/Drive等へ評価し固定Presetでなく因果Lifecycle化 | #327 | MIGRATE |
| #198 Awakening Expression/Autonomy | 覚醒状態をBody/Autonomyへ高レベル投影し固定あくび/伸び/挨拶を作らない | #337 #333 | MIGRATE |
| #199 Awakening実HTTP/SSE検証 | cold/resume/long stop/capability欠損等をIntegrationで確認 | #352 #360 | MIGRATE |
| #201 Memory最適化 | Candidate生成、importance/novelty/persistence/confidence、route、merge/update/contradiction、retrieval | #364 #332 #359 | MIGRATE |
| #207 共有コンテキスト・引継ぎハブ | GitHub live authority、Issue粒度、Verification、Projects管理、設計整合、1 Work=1 lineage | #317運用全体 #314 | OPS-RETAIN |
| #210 内部状態への直接質問 | 内部ラベル/数値の診断説明にせずtyped target/current stateを根拠に自然な自己表現、target外状態代用禁止 | #326 #327 #328 #362 #330 #363 | MIGRATE |
| #211 Generative Body Motion | Skeleton/DOF/limits/current pose、IK/Kinematics、全身協調、no preset、no home reset、3D全方向 | #335 #336 #338 #339 #341 | MIGRATE |
| #212 「もう一回」一般参照 | 直前の行為/発言/話題等をbounded context・execution facts・Memoryからtyped referenceとして解決 | #326 #329 #332 | MIGRATE |
| #213 Viseme同期 | 実TTS発音情報からviseme timeline、母音/閉唇/無音、Body realtimeと全身Motionを並行 | #331 #358 #340 | MIGRATE |
| #214 Character Body Style | Character設定を固定Gender Poseにせず、柔らかさ・軌道・重心・coordination等のStyleへ投影 | #354 #355 #337 | MIGRATE |
| #215 Body Pose Lab簡素化 | 棒人間をBody contract検証モックとして利用しUIはBody判断を持たない | #352 #346 | TOOLING-MIGRATE |
| #217 連続接触の意味区間化 | high-frequency sample数に状態変化を比例させずcontact session/意味区間/body regionを扱う | #349 #327 | MIGRATE |
| #218 会話終了表現誤分類 | farewell/conversation endingとActivity stopをInput Meaningで意味分類し表面語matcherを使わない | #326 | MIGRATE |
| #221 Ctrl+C/pending task | optional Body output切断でCoreを壊さずbackoff/rate-limit/idempotent close/pending taskなし | #322 #350 | MIGRATE |
| #223 Character/Validator Lab | 全体起動なしでproduction pipelineを実LLM検証。preset/export/境界観測 | #352 | TOOLING-MIGRATE |
| #225 発話内容/Character/Voice分離 Parent | 「何を言うか」「どう言うか」「どう音声演技するか」を分離 | #362 #330 #331 #348 | MIGRATE |
| #226 SemanticUtterancePlan | Characterより上流でspeech act/target/proposition/budget/required/forbidden等の発話意味を確定 | #362 | MIGRATE |
| #227 Character Language Realizer | raw内部値を再解釈せず、確定意味をCharacter Profileで自然言語化 | #330 #355 | MIGRATE |
| #228 SpeechPerformancePlan | 言語的な間と音響的な間を分離したengine-independent prosody | #331 #358 | MIGRATE |
| #229 Semantic / Realization Validator | Character speechを独立semantic interpretationしtyped planと比較。finite lexical matcher禁止 | #363 #352 #357 | MIGRATE |
| #235 Character設定ブラッシュアップ Parent | Human-readable人物像を正本にしLanguage/Voice/Bodyへ一貫投影 | #324 | MIGRATE |
| #236 Character Bible | Identity/Personality/Values/Social/Language/Voice/Bodyをユーザーと確定、動的状態と分離 | #354 | MIGRATE |
| #237 Runtime CharacterProfile projection | Character Bible→Language/Voice/Body typed profiles、Profileを人物設定正本にしない | #355 | MIGRATE |
| #240 参考動画クラウド解析 | reference-only ASR/audio/visual analysis、素材直接再利用禁止、人間レビューでCharacter設計へ | #353 | TOOLING-MIGRATE |
| #288 有限自然語辞書全廃 | open-ended NLをkeyword/regex/substringでsemantic authorityにせずfinite fallback禁止 | #326 #362 #330 #363 + system policy | MIGRATE |
| #290 Input Meaning唯一authority | raw user textのspeech act/intent/negation/hypothetical/activity等を下流で再解釈しない | #326 | MIGRATE |
| #291 Confirmation typed semantics | confirmationをregex/phrase listで分類せずtyped semantic resultへ。low confidenceは実行しない | #326 #328 | MIGRATE |
| #292 Character Claim/Budget/Existence typed検証 | claim/question/topic/existenceをfinite regexで判定せずtyped semantic planとexecution facts/closed policyで検証 | #328 #362 #330 #363 | MIGRATE |
| #293 degree語辞書撤去 | intensity/state/certaintyを有限語彙で検出せず独立semantic verification | #362 #330 #363 #357 | MIGRATE |
| #295 Issue graph | Issue parent/dependency/Projects状態をread-only graphとして可視化 | #353 | TOOLING-MIGRATE |
| #303 Semantic Realization再構築 | proposition facet直交化、Structured Outputs、relative semantic verifier、mini baselineでarchitecture評価 | #362 #330 #363 #357 #352 | MIGRATE |
| #311 ChatGPT全チャット議事録 | 開発経緯を削除後も復元可能な歴史資料として永続化。current state authorityにはしない | #207 + history docs | HISTORY-RETAIN |
| #312 System Architecture Visualizer | AST/read-only architecture graph、検索/filter/Render、production authorityなし | #353 | TOOLING-MIGRATE |
| #314 Resume Gate | memory/summaryから状態確定禁止、live GitHub照合、Resume Certificate、multiple lineageでSTOP | #317運用全体 | OPS-RETAIN |

---

# 5. Open PR migration

初回inventoryのOpen PR 23本はV2へ**merge/cherry-pickしない**。要求・設計知見・failure class・Verificationケースだけ回収する。

| PR | Live title | 回収するもの | V2 destination | Disposition |
|---|---|---|---|---|
| #130 | 内部指示器（司令塔LLM）のクラウド検証ラボを追加 | production path再利用Lab、fake/live、preset、Export、存在境界等 | #352、Executive知見→#328 | TOOLING-MIGRATE |
| #203 | Awakening Contextと前回状態SnapshotのPersistence境界を追加する | cold/resume/restart、minimum snapshot、本文/Prompt/Poseを保存しない、persistence failure非致命 | #327 #350 #359 | MIGRATE |
| #204 | Awakening AppraisalとLifecycleを内的状態へ統合する | 前回状態を直接復元せずAppraisal、停止時間減衰、起動因果、固定Preset禁止 | #327 | MIGRATE |
| #205 | Awakening AppraisalをBody表現と自律Interactionへ因果統合する | Bodyへ高レベル状態を投影、Autonomyと同じ因果経路、初期Frameから因果状態 | #337 #333 | MIGRATE |
| #206 | Awakening起動Lifecycleの実HTTP・SSE統合検証を追加する | 実境界Integration、固定neutralでない初期Frame、Lifecycle差、障害縮退 | #352 #360 | MIGRATE |
| #219 | 内部状態への直接質問を自然な自己表現として生成する | typed target、内部状態ラベル説明禁止、target semantic consistency、反復時も逸脱しない | #326 #327 #328 #362 #330 #363 | MIGRATE |
| #224 | Character / Response Validatorの単体検証Labを追加 | Runtime全体なしのCharacter/Validator production-path Lab | #352 | TOOLING-MIGRATE |
| #230 | Character LLMを言語実現専用Realizerへ分離する設計を追加 | Semantics→Character→Performance責務分離、raw internal stateをCharacterへ渡さない | #362 #330 #331 #355 | MIGRATE |
| #231 | SemanticUtterancePlanで発話内容の意味境界を追加 | typed proposition/target/budget、raw数値をPlanへ持たない、What-to-sayをCharacterより上流へ | #362 | MIGRATE |
| #232 | Character LLMをSemantic Planの言語実現専用Realizerへ移行 | Character-facing narrow input、strict output schema、TTS/Body責務除去 | #330 #357 | MIGRATE |
| #233 | Semantic ValidatorとCharacter Realization Validatorを分離 | independent semantic observation、typed comparison、certainty/intensity/unknown failure、finite辞書禁止 | #362 #330 #363 #357 | MIGRATE |
| #234 | Character LabをSemantic Plan / Realization Validator分離後のstackへ更新 | semantic Lab、regression、failure aggregation、Export | #352 | TOOLING-MIGRATE |
| #238 | ゆらCharacter Bibleの初稿を作成する | 確定/要確認/未決定を分離したCharacter draft。ユーザー未確認項目を確定扱いしない | #354 | MIGRATE |
| #241 | 参考動画クラウド解析パイプラインを整備する | reference-only policy、クラウドASR、Drive result、元素材直接再利用禁止 | #353 | TOOLING-MIGRATE |
| #289 | 有限自然語辞書による意味判定を全廃する | Natural Language Lexical Decision Policy、semantic fallback禁止、typed authority | #326 #328 #362 #330 #363 | MIGRATE |
| #296 | Issue親子関係と進行状況をノードグラフで可視化する | official parent/subIssue、Projects fields、routing/selection/Render/secret境界 | #353 | TOOLING-MIGRATE |
| #301 | CI-only: #227/#229 foundational semantic contract | CI-onlyはmergeしない、certainty/optional realization failure classの回帰証跡 | #362 #330 #363 tests | CI-ARCHIVE |
| #302 | Semantic Realization検証の設計を根本再評価 | exact round-tripの脆弱性、facet直交化、Structured Outputs、relative verifier、model matrix | #362 #330 #363 #357 #352 | MIGRATE |
| #304 | Semantic Realization v2へ再構築 | semantic facet/proposition_id/alignment/Structured Output方針。コードは移植しない | #362 #330 #363 #357 | MIGRATE |
| #310 | Character Semantic v2 model matrix Labを追加 | Character/Verifier model独立評価、mini baseline、upper-bound診断、failure class集計 | #352 #357 #363 | TOOLING-MIGRATE |
| #313 | システムモジュール依存関係の可視化GUIを追加 | read-only AST graph、logical module、Render、production metadata不要 | #353 | TOOLING-MIGRATE |
| #315 | ChatGPT作業再開Resume Gateを運用ルール化 | live GitHub authority、STOP、Certificate、Checkpoint、single lineage | #207 #314 / V2運用 | OPS-RETAIN |
| #316 | docs: ChatGPTプロジェクト全チャット議事録を永続化 | 「なぜこうなったか」の履歴資料。current architecture/state正本にはしない | history docs / #207 index | HISTORY-RETAIN |

---

# 6. 単一Legacy Issueに十分記録されていなかった重要ユーザー要求

## R01 発話再生中に次発話生成を進める

**P0 / Architecture invariant**。

前発話の再生待ちと次LLM生成待ちを直列加算しない。

V2: #322 #323 #333 #348 #334 #360、`speech_pipeline_architecture.md`、`concurrency_architecture.md`。

FAIL:

```text
await current_speech_playback_complete()
→ next Appraisal
→ next Executive
→ next Speech Semantics / Character generation
```

fake playbackを5秒→20秒へ伸ばしてもnext generation startを同じ長さだけ遅らせない。候補はbounded、presentation前にrevalidateしstaleなら破棄する。

## R02 Bodyは実装済み動作Presetの選択器にしない

360°全方向、全身協調、複数部位同時、current poseから連続運動、no Home reset、大小jump、自然な腕/関節協調、非指示時の視線/呼吸/微動、Canonical 3Dを維持する。

V2: #335〜#341 #346、`body_architecture.md`。

## R03 入力はText以外へ拡張可能

Voice / Vision / camera-derived event / Touch / Streaming等。Touchはavatar hit、body region、contact start/update/end、sampling-rate independentを扱う。

V2: #349 → #326/#327。

## R04 「もう一回」「それ」「さっきの」の一般参照

Body専用再生ではなく、recent speech/commands、Activity execution facts、Memory等のbounded typed ReferenceContextから解決する。

V2: #326 #329 #332。

## R05 自律性は状態・動機・Goalから生じる

固定timer→固定台詞ではなくEmotion/Desire/Drive/Motivation/Interest/Relationship/Goal/Commitment/Activity/turn facts等からExecutive triggerを発生させる。ユーザー入力で準備中候補を再評価できる。

V2: #327 #328 #333 #348。

## R06 Emotion / Desire / Drive / Moral-Values / Interest

Emotion、Desire、Drive、Motivation、Moral/Values appraisal、target Interest/Curiosity、Relationship、arousal/energyを動的因果状態として扱い、static Character traitと分離する。

V2: #327 #354 #355。

## R07 起動は固定neutralではない

前回state、停止時間、現在時刻/capability等をAppraisalし、その結果としてnonverbal/speech/silenceが生じる。固定あくび/伸び/挨拶Presetを正規設計にしない。

V2: #327 #333 #337 #350 #359。

## R08 Character存在境界と事実性

接続されていない感覚・物理経験を事実として主張せず、capability/execution factより先に「やった」と言わない。Character Definitionで事実性を上書きしない。

V2: #329 #362 #330 #363 #354 #355。

## R09 CharacterとBodyは兄弟Realizer

Character speechからBody命令を暗黙生成せず、Body結果からCharacter意味を決めない。Executiveが確定した高レベル意図からSpeech/Bodyへfan-outする。

V2: #328 #362 #330 #338 #341。

## R10 StreamingはCoreから独立

StreamingはCore PluginでもCore成立条件でもない。大量コメント処理はbounded/aggregatedにしCore認知をblockしない。

V2: #345 #347。

## R11 GUI/Labは判断Authorityを持たない

production DTO/Port/read modelを利用しCore logicをコピーしない。

V2: #351 #352。

## R12 Module単位で設計・開発・試験

```text
Design → Unit → Adjacent Contract → Integration → System Verification
```

全体起動をModule一次品質証明にしない。

V2: system architecture Module Development Gate、#360。

## R13 自由意志と専門Skill AIを分離

最終目標は、ユーザーへの返信器ではなく、自ら会話・配信・ゲーム等を選択する「ゆら」という主体である。

- Executive #328が「何をしたい/する/しない」の最終Authority
- Goal Planner #361は選択済みGoalの実行方法を分解するだけ
- Game Skill #365はframe-levelの専門技能でありGoal Authorityを持たない
- Streaming Skill AIは大量コメント分類等を行えても返答/配信継続の最終Authorityを持たない
- Game/Streamingのrealtime/high-volume loopをCore LLM latencyへ従属させない

V2: #328 #361 #345 #347 #365 #360、`subsystem_architecture.md`。

---

# 7. Legacy failure classes to preserve

## Natural language / semantic authority

- finite keyword/marker/regexが未見paraphraseを漏らす
- lexical fallbackがLLM semantic authorityを破壊する
- `unknown` / certainty / intensityを表面語からexact reconstructするとfalse accept/rejectが増える

V2: #326 external-input authority、#362 speech semantic contract、#330 language realization、#363 independent observation、#357 provider boundary。

## Character

- raw internal valuesをCharacterへ渡すとtarget外状態を代用する
- 内部状態を先に自然語化しすぎるとCharacterが診断レポート化/固定文反復する
- Character Profileが事実決定へ侵入すると意味が変わる

V2: #328 conscious Goal/Action authority、#362 What-to-say、#330 How-to-say、#355 static projection。

## Semantic verification

- Character自身の「意味を保持した」という自己申告だけでは独立検証にならない
- free-form validator outputを最終Authorityにすると新しい意味決定器になる
- finite lexical markerで意味保持を判定するとparaphrase耐性が落ちる

V2: #363 independent Observer + closed typed acceptance policy、#352 model/failure matrix。

## LLM latency / runtime topology

- 責務分離されたLLMを全て数珠つなぎにすると各Provider latencyがcritical pathへ加算される
- slow background cognitionがforeground interactionをstarveし得る
- stale long-running resultを最新stateへcommitすると因果が壊れる

V2: #322 #323 #348 #357 #360。Role分離とruntime invocation graphを分離し、priority/cancel/revision/backpressureを持つ。

## Speech timing

playback完了後に次生成開始すると再生時間+LLM latencyが会話gapへ直列加算される。

V2: #348 non-sequential preparation/presentation。

## Body

finite action/preset、顔だけの動作、home reset、2D renderer制約のCore逆流では自由運動にならない。

V2: #336 #338 #339 #340 #341。

## Memory

raw conversationを無条件長期保存、LLM自由文を直接Memory正本へ書込み、古いMemoryをcurrent truthにする設計は避ける。

V2: #364 Candidate/Reflection、#332 validation/store/retrieval、#359 persistence。

## Runtime / shutdown

optional output未接続時のerror spam、Ctrl+C worker exception/pending task、external failureのCore波及を防ぐ。

V2: #322 #350。

## Validation process

全体起動でしかModule不具合を見られない、test phraseをproduction dictionaryへ合わせる、上位modelだけで構造欠陥を隠すことを避ける。

V2: #352 Labs、Module Development Gate、#357 model/role policy。

---

# 8. Legacy closure policy

本Matrixが存在するだけで旧Issue/PRを即closeしない。

```text
1. Matrix全件mapping
2. V2 destination Issue存在確認
3. V2 canonical docsとの矛盾確認
4. cross-cutting requirement確認
5. #318 reconciliation checkpoint
6. #317 Design Gate全canonical確認
7. 旧PRへsuperseded comment
8. old implementation PR close (unmerged)
9. old Work/Parent Issue close or retained-ops/history classification
10. Project #6をV2 hierarchyへ同期 (#319)
```

旧PR close時コメント例:

```text
Superseded by V2 rebuild #317.
Code is intentionally not merged/cherry-picked.
Requirements/failure knowledge migrated to:
- <V2 Issue(s)>
- docs/architecture/v2/legacy_migration_matrix.md
```

#207/#314等の運用正本は単純close対象にしない。#311/PR #316等の履歴資料も現在設計Authorityではなく歴史資料として保存する。

---

# 9. Migration completion checklist

- [x] Legacy Open Issue 44件をV2 destinationへ対応付け
- [x] 初回Open PR 23本をV2 destination / dispositionへ対応付け
- [x] Awakening / Conversation / Turn / Expression要求回収
- [x] Memory要求を#364 Candidate/Reflectionと#332 Storeへ再分離
- [x] Input Meaning / finite lexical prohibition回収
- [x] Speech Semantics / Character Language / Semantic Verification / Performanceを再分離
- [x] Body freedom / IK / 3D / realtime要求回収
- [x] Touch / multimodal input要求回収
- [x] Pluginの構造定義とPlugin-zero invariantを分離して回収
- [x] Streaming独立Subsystem要件回収
- [x] Game Skill #365を最終目標から追加
- [x] GUI/Lab/tooling要件回収
- [x] graceful degradation/shutdown要求回収
- [x] Resume Gate / single active lineage運用回収
- [x] 発話再生中next-generation要求をP0 invariantとして回収
- [x] LLM Role固定を撤回し非直列Invocation要件を回収
- [x] Cognitive/LLM redesign後のdestination再マッピング
- [ ] #318へ再同期Migration Checkpointを記録
- [ ] #317 Design Gateで全canonicalをユーザー確認
- [ ] 確認後に旧implementation lineageを順次superseded close
- [ ] #319でProjects v2をV2 hierarchyへ同期

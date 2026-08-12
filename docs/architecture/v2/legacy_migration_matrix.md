# AI Liver ゆら V2 Legacy Migration Matrix

Status: Draft / V2 Design Gate
Root: #317
Management work: #318
Canonical architecture: `docs/architecture/v2/system_architecture.md`
V2 branch: `rebuild/v2-foundation`

## 1. 目的

この文書は、V2再構築で旧Issue / PR / design generationを捨てる前に、**重要な要求・不変条件・失敗知見・Verification条件をV2へ回収したことを証明する移行台帳**である。

V2は最古`main@0500a69c75e46e97c0f849c26a4d3d7f1fb138dd`から再構築する。

旧コードをV2へmerge / cherry-pickして継承しない。

```text
Legacy Issue / PR / design / verification history
        ↓
retain requirement / invariant / failure class / test case
        ↓
V2 canonical design + V2 Issue
        ↓
new implementation from the oldest-main V2 lineage
```

---

# 2. Authority snapshot

2026-08-12 GitHub live確認時点:

- Legacy Open Issues: **44**
- Open PRs: **23**
- V2 Issues: #317〜#360
- V2 canonical branch: `rebuild/v2-foundation`

Open PR 23本はGitHub live `is:pr is:open`検索で全件確認した。

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
| #186 起動時の覚醒反応 | 起動を固定neutral/固定挨拶にしない。前回状態・停止時間・現在状態からAppraisalし、Speech/Body/Silenceへ因果接続 | #327 #333 #337 #350 #359 #360 | MIGRATE |
| #187 GUI全画面最新化 | `gui/*`全画面棚卸し、public DTO/read model、接続/切断/再接続、Render/ローカル、実画面Verification | #351 | MIGRATE |
| #189 会話生成・発話準備の因果状態 | 生成中も無反応にしない。turn/process factsとExpression/Discourseを因果接続。固定「考え中モーション」で隠さない | #327 #333 #337 #348 #330 #334 | MIGRATE |
| #190 InteractionProcessSnapshot | 入力受理・生成・検証・Text/TTS/presentation・turn・cancel等の**実行事実**を型付きrevisionで観測 | #321 #333 #348 | MIGRATE |
| #191 Interaction Process Appraisal | 実行事実をattention/uncertainty/commitment/readiness等の評価へ変換し、処理段階→固定Motionにしない | #327 #333 #337 | MIGRATE |
| #192 Expression Appraisal | Emotion/Motivation/Interaction状態をBody/Voice/Silence向け高レベル表現へ統合。固定関節動作へ直結しない | #337 #331 | MIGRATE |
| #193 Discourse Appraisal | 話題距離、bridge、acknowledgement、response obligationをtypedに評価。固定Prefixを使わない | #328 #330 | MIGRATE |
| #194 Turn-taking最終統合 | 通常/自律/中断/TTS failure/長い生成待ちを統合。発話前後の因果とturn返却をSystemで確認 | #334 #348 #360 | MIGRATE |
| #195 旧実行ロードマップ | 旧順序をV2の正本にしない。依存・Start/Target・Verification管理という運用要件のみ維持 | #317 #319 | MIGRATE |
| #196 Awakening Context/Persistence | cold/restart/resume、停止時間、必要最小限snapshot、DB unavailableでも起動 | #327 #350 #359 | MIGRATE |
| #197 Awakening Appraisal/Lifecycle | 起動ContextをEmotion/Desire/Driveへ評価。固定Presetではなく因果Lifecycleとして扱う | #327 | MIGRATE |
| #198 Awakening Expression/Autonomy | 覚醒状態をBody/Autonomyへ高レベルに投影し、固定あくび/伸び/挨拶を作らない | #337 #333 | MIGRATE |
| #199 Awakening実HTTP/SSE検証 | cold/resume/long stop/capability欠損等を最終Integrationで確認 | #360 #352 | MIGRATE |
| #201 Memory最適化 | Candidate→importance/novelty/persistence/confidence→route→merge/update/contradiction→retrieval | #332 #359 | MIGRATE |
| #207 共有コンテキスト・引継ぎハブ | GitHub live authority、Issue粒度、Verification、Projects管理、設計整合、1 Work=1 lineage | #317運用全体、#314 | OPS-RETAIN |
| #210 内部状態への直接質問 | 内部ラベル/数値の診断説明にしない。typed targetとcurrent stateを根拠に自然な自己表現、target外状態を代用しない | #326 #328 #330 | MIGRATE |
| #211 Generative Body Motion | Skeleton/DOF/limits/current pose、IK/Kinematics、全身協調、no preset、no home reset、3D全方向 | #335 #336 #338 #339 #341 | MIGRATE |
| #212 「もう一回」一般参照 | 直前の行為/発言/話題等をbounded contextからtyped referenceとして解決。Body固有処理にしない | #326 #332 | MIGRATE |
| #213 Viseme同期 | 実TTSの発音情報からviseme timeline、母音/閉唇/無音、Body realtimeと全身Motionを並行 | #331 #358 #340 | MIGRATE |
| #214 Character Body Style | Character設定を固定Gender Poseにせず、柔らかさ・軌道・重心・coordination等のStyleへ投影 | #354 #355 #337 | MIGRATE |
| #215 Body Pose Lab簡素化 | 棒人間をBody contract検証モックとして利用。UIがBody判断を持たない | #352 #346 | TOOLING-MIGRATE |
| #217 連続接触の意味区間化 | 高頻度pointer sample数に状態変化を比例させない。contact sessionと意味区間、touch body region | #349 #327 | MIGRATE |
| #218 会話終了表現誤分類 | farewell/conversation endingとActivity stopをInput Meaningで意味分類し、表面語matcherを使わない | #326 | MIGRATE |
| #221 Ctrl+C/pending task | optional Body output切断でCoreを壊さない。backoff/rate-limit、idempotent close、pending taskなし | #322 #350 | MIGRATE |
| #223 Character/Validator Lab | 全体起動なしでproduction pipelineを実LLM検証。preset/export/境界観測 | #352 | TOOLING-MIGRATE |
| #225 発話内容/Character/Voice分離 Parent | 「何を言うか」「どう言うか」「どう音声演技するか」を分離 | #328 #330 #331 #348 | MIGRATE |
| #226 SemanticUtterancePlan | Characterより上流でspeech act/target/proposition/budget/required/forbidden等の意味を確定 | #328 `SystemCommand.speech_intent` + #330 input contract | MIGRATE |
| #227 Character Language Realizer | raw内部値を再解釈せず、確定意味をCharacter Profileで自然言語化 | #330 #355 | MIGRATE |
| #228 SpeechPerformancePlan | 言語的な間と音響的な間を分離。engine-independent prosody | #331 #358 | MIGRATE |
| #229 Semantic / Realization Validator | Character speechを独立semantic interpretationしtyped planと比較。finite lexical matcher禁止 | #330 #357 #352 | MIGRATE |
| #235 Character設定ブラッシュアップ Parent | Human-readable人物像を正本にし、Language/Voice/Bodyへ一貫投影 | #324 | MIGRATE |
| #236 Character Bible | Identity/Personality/Values/Social/Language/Voice/Bodyをユーザーと確定。動的状態と分離 | #354 | MIGRATE |
| #237 Runtime CharacterProfile projection | Character Bible→Language/Voice/Body typed profiles。Profileを人物設定正本にしない | #355 | MIGRATE |
| #240 参考動画クラウド解析 | reference-only ASR/audio/visual analysis、素材直接再利用禁止、人間レビューでCharacter設計へ | #353 | TOOLING-MIGRATE |
| #288 有限自然語辞書全廃 | open-ended NLをkeyword/regex/substringでsemantic authorityにしない。失敗時finite fallback禁止 | #326 #328 #330 + system policy | MIGRATE |
| #290 Input Meaning唯一authority | raw user textのspeech act/intent/negation/hypothetical/activity等を下流で再解釈しない | #326 | MIGRATE |
| #291 Confirmation typed semantics | confirmationをregex/phrase listで分類せずtyped semantic resultへ。low confidenceは実行しない | #326 #328 | MIGRATE |
| #292 Character Claim/Budget/Existence typed検証 | open speechのclaim/question/topic/existenceをfinite regexで判定せず、typed semantics→deterministic facts/budget比較 | #328 #330 | MIGRATE |
| #293 degree語辞書撤去 | intensity/state/certaintyを有限語彙で検出しない。independent semantic verification | #330 #357 | MIGRATE |
| #295 Issue graph | Issue parent/dependency/Projects状態をread-only graphとして可視化 | #353 | TOOLING-MIGRATE |
| #303 Semantic Realization再構築 | proposition facet直交化、Structured Outputs、relative semantic verifier、mini baselineでarchitecture評価 | #330 #357 #352 | MIGRATE |
| #311 ChatGPT全チャット議事録 | 開発経緯を削除後も復元可能な履歴資料として永続化。current state authorityにはしない | #207 + history docs | HISTORY-RETAIN |
| #312 System Architecture Visualizer | AST/read-only architecture graph、検索/filter/Render、production authorityなし | #353 | TOOLING-MIGRATE |
| #314 Resume Gate | memory/summaryから状態確定禁止、live GitHub照合、Resume Certificate、multiple lineageでSTOP | #317運用全体 | OPS-RETAIN |

---

# 5. Open PR migration

V2は以下23本を**merge/cherry-pickしない**。要求・設計知見・failure class・Verificationケースのみ回収する。

| PR | Live title | 回収するもの | V2 destination | Disposition |
|---|---|---|---|---|
| #130 | 内部指示器（司令塔LLM）のクラウド検証ラボを追加 | production path再利用Lab、fake/live、preset、Export、存在境界・Knowledge Gap等の検証知見 | #352、Commander要件は#328 | TOOLING-MIGRATE |
| #203 | Awakening Contextと前回状態SnapshotのPersistence境界を追加する | cold/resume/restart、minimum snapshot、本文/Prompt/Poseを保存しない、persistence failure非致命 | #327 #350 #359 | MIGRATE |
| #204 | Awakening AppraisalとLifecycleを内的状態へ統合する | 前回状態を直接復元せずAppraisal、停止時間減衰、起動因果、固定Preset禁止 | #327 | MIGRATE |
| #205 | Awakening AppraisalをBody表現と自律Interactionへ因果統合する | Bodyへ高レベル有限状態を投影、Autonomyと同じ因果経路、初期Frameから因果状態 | #337 #333 | MIGRATE |
| #206 | Awakening起動Lifecycleの実HTTP・SSE統合検証を追加する | 実境界Integration、固定neutralでない初期Frame、Lifecycle差、障害縮退 | #352 #360 | MIGRATE |
| #219 | 内部状態への直接質問を自然な自己表現として生成する | typed target、内部状態ラベル説明禁止、target semantic consistency、反復時も話題逸脱しない | #326 #328 #330 | MIGRATE |
| #224 | Character / Response Validatorの単体検証Labを追加 | Runtime全体なしのCharacter/Validator production-path Lab | #352 | TOOLING-MIGRATE |
| #230 | Character LLMを言語実現専用Realizerへ分離する設計を追加 | Semantics→Character→Performance責務分離、raw internal stateをCharacterへ渡さない | #328 #330 #331 #355 | MIGRATE |
| #231 | SemanticUtterancePlanで発話内容の意味境界を追加 | typed proposition/target/budget、raw数値をPlanへ持たない、何を言うかをCharacterより上流へ | #328 #330 | MIGRATE |
| #232 | Character LLMをSemantic Planの言語実現専用Realizerへ移行 | Character-facing narrow input、strict output schema、TTS/Body責務除去 | #330 #357 | MIGRATE |
| #233 | Semantic ValidatorとCharacter Realization Validatorを分離 | independent semantic observation、typed comparison、certainty/intensity/unknown failure classes、finite辞書禁止 | #330 #357 | MIGRATE |
| #234 | Character LabをSemantic Plan / Realization Validator分離後のstackへ更新 | semantic Lab、12-case regression、failure aggregation、Export | #352 | TOOLING-MIGRATE |
| #238 | ゆらCharacter Bibleの初稿を作成する | 確定/要確認/未決定を分離したCharacter draft。**ユーザー未確認項目はV2で確定扱いしない** | #354 | MIGRATE |
| #241 | 参考動画クラウド解析パイプラインを整備する | reference-only policy、クラウドASR、Drive result、元映像/声/台詞/モーションの直接再利用禁止 | #353 | TOOLING-MIGRATE |
| #289 | 有限自然語辞書による意味判定を全廃する | Natural Language Lexical Decision Policy、semantic fallback禁止、typed interpreter authority | #326 #328 #330 | MIGRATE |
| #296 | Issue親子関係と進行状況をノードグラフで可視化する | official parent/subIssue、Projects fields、routing/selection/Render/secret境界 | #353 | TOOLING-MIGRATE |
| #301 | CI-only: #227/#229 foundational semantic contract | CI-onlyはmergeしないという運用、certainty/optional realization failure classの回帰証跡 | #330 test cases | CI-ARCHIVE |
| #302 | Semantic Realization検証の設計を根本再評価 | exact round-tripの脆弱性、facet直交化、Structured Outputs、relative semantic verifier、model matrix | #330 #357 #352 | MIGRATE |
| #304 | Semantic Realization v2へ再構築 | v2 semantic facet/proposition_id/alignment/Structured Output実装方針。**コードは移植しない** | #330 #357 | MIGRATE |
| #310 | Character Semantic v2 model matrix Labを追加 | Character/Verifier model独立評価、mini baseline、upper-bound診断、failure class集計 | #352 #357 | TOOLING-MIGRATE |
| #313 | システムモジュール依存関係の可視化GUIを追加 | read-only AST graph、logical module、Render、production metadata不要 | #353 | TOOLING-MIGRATE |
| #315 | ChatGPT作業再開Resume Gateを運用ルール化 | live GitHub authority、STOP、Certificate、Checkpoint、single lineage | #207 #314 / V2運用 | OPS-RETAIN |
| #316 | docs: ChatGPTプロジェクト全チャット議事録を永続化 | 「なぜこうなったか」の履歴資料。current architecture/state正本にはしない | history docs / #207 index | HISTORY-RETAIN |

---

# 6. 単一Legacy Issueに十分記録されていなかった重要ユーザー要求

V2では「Open Issueに残っていなかったから削除」としない。開発初期から繰り返し要求された以下をcross-cutting requirementsとして明示回収する。

## R01 発話再生中に次発話生成を進める

**重要度: P0 / Architecture invariant**

開発初期からの要求:

> 現在の発言が終わるまで次の発話内容生成処理が滞らないこと。
> 前発話の再生待ちと次LLM生成待ちが直列加算され、発話ごとの間隔が異常に長くならないこと。

V2:

- #348 Speech Pipeline
- #322 Runtime Kernel
- #333 Autonomy / Turn
- #334 Brain Integration
- #360 System Integration
- `docs/architecture/v2/speech_pipeline_architecture.md`

必須FAIL条件:

```text
await current_speech_playback_complete()
→ next Appraisal
→ next Commander
→ next Character generation
```

必須テスト:

- fake playbackを5秒→20秒へ伸ばしてもnext generation startが15秒後ろへ押されない
- Speech A再生中にSpeech Bをprepare可能
- Bはpresentation直前にrevalidateし、staleなら再生しない
- queueはbounded

## R02 Bodyは実装済み動作Presetの選択器にしない

要求:

- 360°全方向。左右だけでなく上下・前後・斜め
- 顔だけでなく全身
- 複数方向・複数部位を同時に動かせる
- current poseから連続運動
- Home/Neutralへ毎回戻らない
- ジャンプは膝・腰・足首・腕・rootを協調
- 小さなjumpと大きなjumpの違い
- 手振り、腕上げ等も肩/肘/手首を自然に協調
- 非指示時も視線・呼吸・微動がある
- 2D/Live2Dの制約をCanonical 3D能力へ逆流させない

V2: #335〜#341、#346。

## R03 入力は将来Text以外も含む

- Voice
- Vision / camera-derived event
- Touch / pointer
- Streaming等Subsystem input

Touchでは:

- ゆらへ触れたか
- どの身体領域へ触れたか
- contact start/update/end
- sampling rate independent

V2: #349 → #326/#327。

## R04 「もう一回」「それ」「さっきの」の文脈参照

Body専用再生ではなく、過去会話・Activity execution facts・Memoryから一般参照として解決する。

V2: #326 #332。

## R05 自律性は状態・動機から生じる

- 起動するたび固定挨拶をしない
- N秒無操作→固定台詞のような人格ロジックにしない
- PC/環境等はInput Gatewayから受領済みtyped eventとして利用
- Emotion/Desire/Drive/Motivation/Interest/Relationship/turn factsからCommanderが発話/沈黙/観察/Activityを決定
- ユーザー入力で準備中自律候補を再評価できる

V2: #327 #328 #333 #348。

## R06 Emotion / Desire / Drive / Moral-Values / Interest

動的内部状態を一つの「mood」へ潰さない。

- Emotion
- Desire（過去に7種の概念を検討）
- Drive
- Motivation
- Moral / Values appraisal
- target-specific Interest / Curiosity
- Relationship
- arousal / energy

static Character traitとは分離する。

V2: #327 #354 #355。

## R07 起動は固定neutralではない

前回state、停止時間、現在時刻/capability等をAppraisalし、結果としてnonverbal/speech/silenceが生じる。

固定「あくび」「伸び」「おはよう」Presetを正規設計にしない。

V2: #327 #333 #337 #350 #359。

## R08 Character存在境界と事実性

- ゆらは仮想AIとしての存在境界を持つ
- 接続されていない感覚・物理身体経験を事実として主張しない
- capability/execution factsより先に「やった」と言わない
- Character Definitionは事実性を上書きしない

V2: #329 #330 #354 #355。

## R09 Character/Bodyは兄弟Realizer

Character speechから暗黙にBody命令を生成しない。
Body結果からCharacter意味を決めない。
Commanderの同じSystemCommandに従う。

V2: #328 #330 #338 #341。

## R10 StreamingはゆらCoreから独立

StreamingをCore PluginまたはCore成立条件にしない。

V2: #347。

## R11 GUI/Labは判断authorityを持たない

GUI/Labはproduction DTO/Port/read modelを利用し、Core logicをコピーしない。

V2: #351 #352。

## R12 Module単位で設計・開発・試験する

全体起動でしか品質確認できない構造を避ける。

```text
Design
→ Unit
→ Adjacent Contract
→ Integration
→ System Verification
```

V2: system architecture Module Development Gate、#360。

---

# 7. Legacy failure classes to preserve as regression knowledge

## Natural language

- finite keyword/marker/regexが未見paraphraseを漏らす
- lexical fallbackがLLM semantic authorityを破壊する
- `unknown` / certainty / intensity等を表面語からexact reconstructするとfalse accept/rejectが増える

V2 response:
- #326 sole input semantic authority
- #330 independent output semantic verification
- #357 strict structured provider boundary

## Character

- raw internal valuesをCharacterへ渡すとtarget外状態を代用する
- Plannerが内部状態を先に自然語化するとCharacterが診断レポート化/固定文反復する
- Character Profileが事実決定へ侵入すると意味が変わる

V2 response:
- #328 What-to-do/what-to-say authority
- #330 language realization only
- #355 static profile projection

## Speech timing

- playback完了後に次生成開始すると再生時間+LLM latencyが会話gapへ直列加算される

V2 response:
- #348 two-lane asynchronous architecture

## Body

- action name→finite pose axisでは自由運動にならない
- face/headだけ動いて全身が連動しない
- home resetで生物的連続性が失われる
- 2D renderer制約をCoreへ持ち込むと3D能力が縮む

V2 response:
- #336/#338/#339/#340/#341

## Runtime

- optional Body output未接続時に高頻度error spam
- Ctrl+Cでworker exception / pending task
- external output failureがCore loopへ波及

V2 response:
- #322 #350

## Validation process

- module不具合確認に全体起動を使うと他領域の問題が混ざる
- test phraseをproduction dictionaryへ合わせると設計欠陥を隠す
-上位modelだけPASSしても小型production baselineの構造欠陥を隠し得る

V2 response:
- #352 Labs
- Module Development Gate
- #357 role/model policy

---

# 8. Legacy closure policy

本Matrixが存在するだけで旧Issue/PRを即closeしない。

順序:

```text
1. Matrix全件mapping
2. V2 destination Issue存在確認
3. V2 canonical docsとの矛盾確認
4. cross-cutting requirement確認
5. #318 checkpoint
6. 旧PRへsuperseded comment
7. old implementation PR close (unmerged)
8. old Work/Parent Issue close or retained-ops/history classification
9. Project #6をV2 hierarchyへ同期 (#319)
```

旧PRを閉じる際は、少なくとも次をコメントする。

```text
Superseded by V2 rebuild #317.
Code is intentionally not merged/cherry-picked.
Requirements/failure knowledge migrated to:
- <V2 Issue(s)>
- docs/architecture/v2/legacy_migration_matrix.md
```

`#207`, `#314`等の運用正本は単純close対象にしない。

`#311/PR #316`等の履歴資料も「現在設計」としてではなく歴史資料として保存する。

---

# 9. Migration completion checklist

- [x] Legacy Open Issue 44件をV2 destinationへ対応付け
- [x] Open PR 23本をV2 destination / dispositionへ対応付け
- [x] Awakening要求回収
- [x] Conversation/Turn/Discourse/Expression要求回収
- [x] Memory要求回収
- [x] Input Meaning / finite lexical prohibition回収
- [x] Character semantic / Language Realizer / Performance要求回収
- [x] Body freedom / IK / 3D / realtime要求回収
- [x] Touch / multimodal input要求回収
- [x] Plugin zero-core requirement回収
- [x] Streaming独立Subsystem要件回収
- [x] GUI/Lab/tooling要件回収
- [x] graceful degradation/shutdown要求回収
- [x] Resume Gate / single active lineage運用回収
- [x] **発話再生中next-generation要求を独立P0 invariantとして回収**
- [ ] #318へMigration Checkpointを記録
- [ ] #317 Design Gateでユーザー確認
- [ ] 確認後に旧implementation PRを順次superseded close
- [ ] #319でProjects v2をV2 hierarchyへ同期

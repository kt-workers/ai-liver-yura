# AI Liver ゆら 作成プロジェクト 全チャット議事録・開発履歴

- 対象: ChatGPTプロジェクト「AI Liver ゆら 作成プロジェクト」
- 記録基準日: 2026-08-12
- Repository: `ktan514/ai-liver-yura`
- GitHub Projects v2: owner `ktan514` / project number `6` / 「プロジェクトゆら」
- 管理Issue: #311
- 共有コンテキスト正本: #207

## 0. 目的・位置付け

この文書は、ChatGPTプロジェクト内のチャットを削除しても、AI Liver「ゆら」の開発経緯を復元できるようにする永続議事録である。単なる会話要約ではなく、何を問題とし、なぜその設計を採用し、何を撤回し、どのIssue/PR/branchへ接続し、何が未完了かを追跡する。

情報源は、ChatGPTプロジェクトで参照可能な会話履歴・引き継ぎコンテキストと、GitHub Issue / PR / branch / docs / Projects v2である。逐語ログを取得できない箇所は推測で補わず、GitHub側の成果物で補完した。

現在の進捗を知る場合の優先順位は、(1) GitHub ProjectのStatus/工程/Start date/Target date、(2) 対象Issue本文と最新コメント、(3) PR、(4) 最新設計書、(5) 本書。本書は「なぜ現在の形になったか」を保存する履歴正本である。

---

# Part I. プロジェクト内チャットの時系列議事録

## 1. 2026-07-26 — AI Liver ゆら GitHub Wiki構成・運用設計

### 議題
`ai-liver-yura`のWikiに何を記載し、Wiki / `docs/` / Issue / PRの責務をどう分けるか。

### 決定
- Wikiは利用者・開発者向けの入口・索引として使う。
- 実装と同じバージョン管理が必要な技術設計は`docs/`を正本にする。
- Issue/PRは作業状態・変更単位・議論履歴を管理する。
- Wikiそのものを唯一の正本にはしない。
- 後の#207「共有コンテキスト・引き継ぎハブ」につながる「入口を一つ作る」思想の前段となった。

## 2. 2026-08-03 — 入力意味解析LLM・内部司令LLM分離実装

### 問題
Situation Evaluatorが、入力意味理解、発話行為認識、内部状態統合、Character LLMへの指示、Activity選択まで混在しており、誤りの責務を切り分けにくかった。

### 決定
A. 入力意味解析LLMは、自然言語を`StructuredInputMeaning`等の型付き意味表現へ変換する。「何を言われたか」を解釈する責務。

B. 内部司令LLMは、入力意味、Emotion / Desire / Drive、Activity状況、存在境界を受け、「それを受けてどうするか」を決める。Characterへの応答目的、Activity、質問予算、新規話題予算、発話/非発話等を扱う。

Character LLMは後段の「どう言うか」に寄せ、意味解析や全体方針を背負わせない。

### 長期的発展
この分離は、2026-08-12時点では概ね次へ細分化された。

```text
Raw Input
→ Input Meaning (semantic authority)
→ Internal Directive / Response Semantics
→ SemanticUtterancePlan
→ Character Language Realizer
→ SpeechPerformancePlan
→ TTS
```

## 3. 2026-08-03 — 内部指示器ラボのブラウザ検証環境構築

### 目的
全Runtimeを起動せず、Internal Directiveを実LLMで単体検証できるブラウザLabをRender上に作る。ローカルPCがない環境からも検証できるようにする。

### 運用
- 検証branchは最新`develop`から作る。
- 対象機能branchの内容を検証branchへ取り込む。
- Labを本実装branchの正本にはしない。
- 実装統合と検証環境を分離する。

### UI/検証項目
StructuredInputMeaning、Emotion/Drive、利用可能Activity、進行中Activity、Character Profile/存在境界、プリセット、JSON編集、折りたたみ、内部状態グラフ、Exportを用意。入力意図整合、内部状態反映、不要Activity、質問/新規話題予算、存在境界を確認。

実際にRenderへデプロイし、画面デザイン・使いやすさ・検証内容・初期モデルの結果はいずれも良好と評価された。

この経験から、検証順を「モジュール単体→隣接契約→サブシステム結合→全体Verification」とする思想が強化された。

## 4. 2026-08-03〜08-04 — 内部指示器ラボ・InternalDirective検証

Internal Directive LabのExportケースをChatGPTへ戻し、入力意図・内部状態・存在境界との整合を評価した。

代表例では、既存Knowledge Gapへの回答をユーザーが提供した場合に、再質問や無関係なActivityへ逸れず、Gap解消を扱えるかを確認。

重要な結論は、Internal Directiveを単なる「LLM向けプロンプト」ではなく、型付きの中間意思決定契約として扱うこと。Markdown/JSON Exportも再現可能な検証手段として有効と確認された。

## 5. 2026-08-04 — アバター自由動作設計・Body制御方式の再構築

### 問題
右を見る、腕を上げる、手を振る等の実装済み動作を固定Action/Poseへ増やしていくと「プリセット集」になり、未知の複合動作や自然な身体表現へ拡張できない。

ユーザーから「結局実装した動きしかできないならプリセットと変わらない」と指摘され、Bodyをもっと自由に動かすことを要求された。

### 決定
- LLM群は意味・意図・動機・Activity・表現意図を決める。
- Bodyは関節・姿勢・視線・口・微動をリアルタイムに実現する。
- 固定モーション名ではなく、current poseから次のpose/trajectoryを連続生成する。
- 明示的な「右手を上げて」等は主経路を置換する固定Presetではなく、一時的な高レベルMotion Goal/Constraintとして扱う。
- 「もう一回やって」はBody固有フレーズ辞書ではなく、過去会話・Activity・過去行為の一般参照解決として分離する。

### 要求された自由度
360度全方向（上下・左右・前後・斜め）、視線/頭/首/胴体協調、左右複合動作、しゃがみ、大小ジャンプ、膝・腰・腕協調、非指示時の自然な微動、Neutral/Homeへのスナップバック禁止。

途中で実装がプリセット化へ寄ったため、プリセット化前の地点または最新developからbranchを作り直す判断も行われた。

後にBody自由動作は#211へ、一般参照解決は#212へ整理された。

## 6. 2026-08-06 — 会話挙動改善・記憶最適化とIssue整理

複数問題を場当たりで同時修正せずIssueへ分離。

### 唐突な発話
固定「考え中アニメーション」を挿入するのではなく、内部処理・動機・会話準備が進んだ因果の結果として表情/視線/Body/沈黙が変化し、自然に発話へつながる設計を求めた。後に#189〜#194のInteraction Process / Expression / Discourse Appraisalへ発展。

### GUI
`gui/*`が最新Core/APIへ追従していない可能性があり、後に#187「GUI全画面最新化・デザイン統一・動作棚卸し」へ。

### Memory
保存判断、要約、統合、重複排除、想起の最適化が不足。高優先Issueを先に処理するため後続化し、#201としてBacklog管理。

### Verification
実画面・実機のユーザー確認が必要なものは、コード完成でDoneにせず`Verification`へ移す運用を確認。

## 7. 2026-08-06 — GitHub Projects「プロジェクトゆら」運用設計

GitHub Projects v2をChatGPT・Codex・人間の共同作業台帳にする。

管理対象はIssue、PR、Status、優先度、工程、開始/終了予定、Verification、Blocked等。

推奨Status:

```text
Backlog → Ready → In progress → Review → Verification → Done
```

外部依存はBlocked。Render、Live2D、VOICEVOX等の実確認が必要ならVerificationを経る。

ChatGPT用アカウント`ch4t9pt`はrepo write権限を持つ。一方、当時のChatGPT connectorではProjects v2 field操作が十分でなかったため、Codex + `gh project`/GraphQL併用方針となった。

最大の狙いは、新規チャットでもProjectから「何をしているか、次は何か、Verification/Blockedは何か」を復元し、チャットを作業正本にしないこと。

## 8. 2026-08-08 — GitHub Projects v2 運用ルール・基準情報管理

Codexで取得したProjects v2 Snapshotを基準情報化。

固定情報:
- owner `ktan514`
- project number `6`
- repo `ktan514/ai-liver-yura`

運用原則:
- 設計→実装の順。
- コード変更時は関連docsも更新。
- `main` / `develop` / `feature/gui-development` / `feature/core-development`へ直接作業コミットしない。
- 作業branch + PRを使う。
- 検証専用branchと本実装branchを分離。
- 実機確認はVerification経由。
- 同じ問題を複数Issueへ重複させず、独立して完成/検証できる単位へ分ける。

大量の古いremote branch問題は#208で非破壊監査され、protected / active / verification / blocked-stacked / external reference / integrated / superseded / orphaned unique work / unknown等へ分類する考え方になった。

#207が共有コンテキスト・引き継ぎハブとして整備され、通常の新規チャット復帰では全履歴再走査よりProject/Issueの正本を読む運用が定着した。

## 9. 2026-08-08 — 作業進捗と動作設計

Body実画面検証で、左右のみで上下/斜めが弱い、360度を満たさない、ジャンプ/膝曲げ/全身協調ができない、大ジャンプと小ジャンプの身体力学的差を表現できない等を再確認。

腕の左右は改善し、「右を見ながら左手を挙げて」等の複合動作は一部成立。一方、見る方向の左右反転が残った時期もあった。

ユーザーは「同じことを複数Issueで対応しない」ことを強く要求。Bodyは#211へ集約し、Skeleton Profile、joint hierarchy、DOF/limits、IK/Kinematics、current pose起点trajectory、high-level BodyMotionGoal、解剖学的left/right、mirrorはRenderer責務、という正規構造へ整理された。

## 10. 2026-08-09 — チャット名再設定提案

プロジェクト内チャット名を内容が分かる名称へ整理し、新規チャット引き継ぎ時に参照先を判断しやすくすることを検討。

ただし恒久策はチャット名整理ではなく、Project/Issue/docs/#207/本書へ作業正本を移すことと整理された。

## 11. 2026-08-11 — Issue親子関係可視化

Issue増加により、親子・依存・進行状況を表だけでは把握しづらくなったため、ノード/エッジで表示する管理GUIを作成。

要求:
- ツリー/グラフ表示。
- ノードクリックで詳細。
- 進行中が一目で分かる。
- Render/ローカル両対応。
- open以外も切替表示。
- ノードと線の重なりを減らす。
- 選択ノードから伸びるedgeを強調。
- 人工的な2列固定ではなく可読性優先配置。

#295へ正規要件を集約。GitHub正式parent/subissuesを親子正本、本文Parent/Depends onは互換fallback、Project fieldを表示し、read-only visualizationとして扱う。Project正本自体を置換しない。

## 12. 2026-08-12 — システム視覚化ツール

Issueだけでなく、システムのモジュール・責務・依存・データフローをノード/エッジで把握する画面を作りたいという新規議題。

対象例はInput Meaning、Internal Directive、Emotion/Desire/Drive、Memory、Activity、Character、Speech、Body、Avatar、GUI、Plugins/Subsystems。

今後の論点:
- 正本データを何にするか（docs/manifest/import graph/runtime dependency等）。
- 物理importと論理責務を分けるか。
- モジュール単位、Port/Adapter、Event flowをどう表すか。
- 変更影響範囲の可視化。
- Issue/設計書/コードへのリンク。

---

# Part II. 議題別統合履歴

## 13. Coreアーキテクチャと責務分離

プロジェクト初期からPython 3.10.5 + asyncioを基盤に、Activity Runtime / Event Queue / Activity Manager / Scheduler / Ports & Adaptersを中心とするイベント駆動設計を採用。配信専用アプリではなく、**自律的に感情・思考・活動を持つキャラクター本体がCoreで、配信は出力の一つ**と再定義された。

責務は継続的に分割され、Situation Evaluator一体型からInput Meaning / Internal Directiveへ、さらにResponse Semantics / SemanticUtterancePlan / Character Language Realizer / SpeechPerformancePlanへ細分化された。

BodyはCharacterの従属物ではなく、同じ上位Intention/Expressionを言語と身体へそれぞれ実現する兄弟Realizerとして扱う。

## 14. Input Meaning / Semantic Validation

自然言語を有限キーワード/regex/固定phrase辞書で直接意味判定する方式を禁止する方向へ進化。

重要Issue:
- #218 会話終了表現をActivity stopへ誤分類しない。
- #212 「もう一回」等を過去会話/Activity/行為の一般参照として解決。
- #288 repository-wideで有限自然語辞書をsemantic authorityから排除。
- #290 Input Meaningを唯一のsemantic authorityへ。
- #291 confirmationをtyped semanticsへ。
- #292 claim/budget/existence検証をtyped semanticsへ。
- #293 degree語辞書撤去。
- #303 Semantic Realization意味保持を再設計し、軽量モデル基準でも安定する契約へ。

原則は、後段Runtimeがraw user textを再解釈せず、Input Meaningの型付き意味を正本として使うこと。

## 15. Emotion / Desire / Drive / Morality

Emotionを単なる表示値にせず、Perception/Event→Appraisal→Emotion/Desire/Drive→Motivation→Interaction Intention→Activity/Expression→Character/Body/Voice/Silenceという因果へ組み込む。

Emotionだけでは「何をしたいか」が不足するため複数Desire/Driveを導入。curiosityは全体的感情というより対象へのinterestとして扱う方向を検討。

Morality/善悪も「善い/悪い固定ルール」ではなく、Characterの価値観・状況・安全境界との関係で扱う構想。

Static CharacterとDynamic Stateを分離し、Character Bible/Profileは静的な人格・価値観・話し方・声・身体表現傾向を持ち、Emotion/Desire/Relationship/Memory/Activity等は動的状態とする。

## 16. 会話品質・自律発話・Turn-taking

初期問題は、回答後の一方的な話題膨張、定型冒頭、質問数の不自然さ、海テーマ偏重、起動直後の喋りすぎ/無言、発話開始の唐突さ。

固定phraseや固定演出で隠さず、状況・内部状態・会話プロセスを型付き評価して自然な結果を生む設計を採用。

発話前の気配は#189〜#194で、Runtimeが確定した会話処理事実→InteractionProcessSnapshot→Appraisal→Expressionへ流し、Face/Gaze/Body/Voice/Silenceへ反映する方針。

Discourse Appraisalではtopic distance、acknowledgement need、response obligation、initiative等を評価し、橋渡し表現をCharacterが自然に実現する。固定「なるほど」挿入ではない。

question budget / new direction budgetも内部司令/Response Semantics側で管理し、ユーザーが単に回答しただけなのに新しい質問を連打しない。

## 17. Memory・会話履歴・参照解決

Memoryは過去文章保存だけではなく、将来の会話・Activity・Relationshipへ必要な情報を取り出す機構。

「もう一回」「それ」「さっきの」等はBodyフレーズ辞書ではなく、短期会話履歴、Activity Result、発話履歴等から一般参照を構造化する。

#201ではMemory Candidate→importance/novelty/persistence/confidence→Memory Router→Short-term/Episodic/Semantic/Relationship/Preference/Activity Memory→consolidation→retrieval ranking等の最適化を後続計画として管理。

## 18. Body / Avatar / Live2D

Live2DはCoreそのものではなく、Canonical Body表現をモデル固有Parameterへ投影するAdapter/Subsystem。棒人間はLive2D完成前にBodyPoseFrameを検証する軽量mock。

Bodyの正規路線は固定Pose/PresetではなくGenerative Motion:

```text
High-level Motion Goal
+ Current Pose
+ Skeleton / DOF / Joint Limits
+ Character Body Style
→ Motion Planner
→ IK / Kinematics
→ trajectory
→ continuous BodyPoseFrame
```

「360度」はyaw一周ではなく3D空間の全方向。Bodyのleft/rightはゆら自身の解剖学的左右で、鏡像表示はRenderer/Adapter責務。

ジャンプはroot上下だけでなくpreparation、hip/knee/ankle flex、extension、airborne、landingを連続計画する。非指示時も視線探索、呼吸、重心変化、瞬き等の自然な低レベル微動を持つ。

口形は単純mouth_open周期ではなく、TTSの発音/Viseme timelineへ同期（#213）。同じMotion GoalでもCharacter Profile由来Body Styleで柔らかさ・振幅・重心・肘/手首等を変える（#214）。

## 19. 起動・Awakening

起動時にneutral無表情・呼吸だけで、自発反応がない問題を改善。固定「おはよう」や固定あくびではなく、Process Start→Awakening Context→Appraisal→Emotion/Desire/Drive→Motivation→Interaction Intention→Expression/Activity→Face/Gaze/Body/Speech/Silenceの因果で起動反応を決める。

#186 Parent、#196 Context/Persistence、#197 Appraisal/Lifecycle、#198 Expression/Autonomous Interaction、#199 Final HTTP/SSE/実画面Verificationへ分割。

再起動時の必要最小限snapshotを保存し、会話本文やraw promptそのものをAwakening永続状態にはしない。

## 20. GUI / 検証Lab / 可視化

GUIはCoreの能力上限を決めない。Inner State Visualizer、Configuration Harbor、Internal Directive Lab、Body Pose Lab、Character/Response Validator Lab、Issue Graph等を問題領域別検証基盤として整備。

#187でGUI全画面の最新化・デザイン統一・動作棚卸しを管理。#215ではBody Pose Labを「多機能本番画面」ではなくGenerative Bodyの3D検証mockへ簡素化する方向。

Issue Graph #295の経験をSystem Graphへ展開する構想が8/12に開始。

## 21. Streaming / OBS / YouTube / TTS

StreamingはCoreキャラクターから分離し、YouTube/OBS/コメント/Ranking/Moderation/Health等をSubsystemとして整理。

管理画面ではログ、自動更新、進行表、終了処理を検証。Fake Adapterでvertical flowを成立させ、その後実OBS→YouTube認証→Live Chatへ段階的に切り替える。

TTSはVOICEVOX等をAdapterとして扱い、Character LLMがengine固有speed/pitch実数を直接決めず、SpeechPerformancePlanを介する。チャット画面テキストと音声の厳密同期は不要だが、Body/Live2Dと発音/Viseme同期は重要。

## 22. Plugins / Games

Games固有処理をCore Runtime設定から切り離し、Game Subsystem契約へ移行。Gateway/DTO/Null implementationを持ち、Coreはゲーム固有ロジックを持たない。

## 23. Infrastructure / CI / Render / PostgreSQL

CI長時間化では、最初から本体ロジックを変更せず、テスト側interval/time等を先に改善する方針。

Renderは出先からのGUI/Lab検証に利用。外部デプロイが特定branchを直接参照する場合は、Git ancestry上統合済みでも自動削除しない。

Docker PostgreSQLをTopic Memory等に利用し、初期化script/READMEを整備。

Body output未接続時のCtrl+C/pending task問題を#221へ分離し、Optional Output未接続がCore全体を壊さない原則を置く。

## 24. GitHub運用・branch・PR

- branch名に作業者名を入れず`feature/`, `fix/`, `refactor/`, `docs/`, `test/`等の目的名を使う。
- ChatGPT作業のcommit authorは専用アカウント`ch4t9pt`。
- `main`, `develop`, `feature/gui-development`, `feature/core-development`へ直接作業コミットしない。
- 原則1 Issue = 1 Draft PR。独立採用/延期できる責務を混ぜない。
- #208で約150 remote branchを非破壊監査し、未回収workは古branchを直接mergeせず最新develop上へIssue単位で回収。
- Project fieldとしてStatus、作業種別、領域、優先度、工程、Start date、Target date、Iteration/Quarter、Assigneesを使う。

---

# Part III. 重要な前史

## 25. 2026-07-01〜07-06 — 基盤・命名・設定方針
- Python 3.10.5 + PyQt6 + asyncioを前提に開発。
- AIライバー名は「星波ゆら（ほしなゆら）」へ確定。
- 設定ロード失敗/必須不足/型ミスはdefault継続せず異常終了。
- ターミナル/外部アクセスは権限境界を持ち、指定パス配下のみ許可したいという要求。

## 26. 2026-07-12〜07-15 — Activity/会話継続
output unit/action ID追跡、音声優先度、OngoingActivity、ActivityTurn、会話中の自律発話抑制、中断話題管理等の設計を整備。

## 27. 2026-07-16〜07-18 — Streaming Admin
ログ、自動更新、最新追従、配信枠/進行表、quit/Ctrl+Cを改善。Fake AdapterでStreaming vertical flowを検証後、実OBS→YouTube認証→Live Chatへ進む段階戦略。

## 28. 2026-07-22〜07-24 — 自律エージェント・GUI分離・GitHub
PC常駐構想、コンソール直接入力と画面/キーボード観測の権限分離、観測を命令扱いしない原則、自律発話の状況判断、Inner State Visualizer/Web会話画面分離、branch/commit運用、ChatGPT用GitHubアカウントを整理。

## 29. 2026-07-27〜07-30 — Render / GUI / DB / Game
RenderでInner State Visualizer公開、設定画面海中UI、Docker PostgreSQL初期化/README、Game Subsystem分離を実施。

## 30. 2026-07-31〜08-02 — Character性・欲望・善悪・好奇心・触覚
EmotionだけでなくDesire/Moralityを検討。実装に3脳モデルはないため事実に合わせる。curiosityを対象interestとして検討。接触はクリック/ドラッグに加えて「ゆらに触れたか」「どこに触れたか」が必要となり、連続接触は後に#217へ。

---

# Part IV. 2026-08-12時点の正規設計スナップショット

## 31. 全体因果構造

```text
Perception / User Input / Memory / Environment
            ↓
Input Meaning / Semantic Interpretation
            ↓
Situation / Appraisal
            ↓
Emotion / Desire / Drive / Relationship
            ↓
Motivation
            ↓
Interaction Intention / Internal Directive
            ↓
Activity + Response Semantics + Expression Appraisal
            ↓
    ┌─────────────────────┬────────────────────────┐
    ↓                     ↓
SemanticUtterancePlan   BodyMotionGoal / Expression
    ↓                     ↓
Character Language      Body Realizer
Realizer                + Skeleton/IK/Kinematics
    ↓                     ↓
CharacterUtterance      continuous BodyPoseFrame
    ↓                     ↓
SpeechPerformancePlan   Avatar Adapter
    ↓                     ↓
TTS / pronunciation    Live2D / 3D / Stick Figure
    ↓
Viseme timeline ─────────→ Body mouth layer
```

CharacterとBodyは兄弟Realizer。Characterの文章をBodyが模倣する構造ではない。

Static Character（Character Bible/Profile、Voice Style、Body Expression Style）とDynamic State（Emotion、Desire/Drive、Relationship、Memory/Interest、Activity）を混ぜない。

## 32. 重要な「やらないこと」

1. 自然言語の有限辞書/regex/substringを意味authorityにしない。
2. Bodyを`raise_right_hand`等の固定Pose/Presetライブラリにしない。
3. 発話の唐突さを固定吸気/毎回首傾げ/毎回「なるほど」等で隠さない。
4. Character LLMへEmotion事実判定、TTS engine実数、Body関節角まで解釈させない。
5. 2D GUIの都合をCanonical 3D Bodyの能力上限へ逆流させない。
6. ChatGPTチャットを作業正本にせず、要望→Issue、長期方針→docs/ADR、進捗→Project、実装→PR、Verification→Project Statusへ昇格する。

---

# Part V. 主要Issue索引

## 管理
- #195 実行ロードマップ
- #207 共有コンテキスト・引き継ぎハブ
- #208 remote branch棚卸し
- #216 Projects v2 field同期
- #311 本議事録

## Input Meaning / Semantic
- #212 一般参照解決
- #218 会話終了誤分類
- #288 有限自然語辞書semantic decision全廃
- #290 Input Meaning semantic authority一本化
- #291 Confirmation typed semantics
- #292 Claim/Budget/Existence typed semantics
- #293 degree語辞書撤去
- #303 Semantic Realization意味保持再設計

## 発話 / Character
- #210 内部状態直接質問の不自然な応答
- #223 Character / Response Validator Lab
- #225 発話内容・Character言語実現・音声演技分離Parent
- #226 SemanticUtterancePlan
- #227 Character Language Realizer
- #228 SpeechPerformancePlan
- #229 Semantic Validator / Character Realization Validator分離
- #235 Character設定ブラッシュアップParent
- #236 Character Bible
- #237 Character Bible→型付きCharacterProfile
- #240 参考動画クラウド日本語ASR/音声解析

## 会話因果 / Turn-taking
- #189 会話準備の因果状態が表現へ反映されず唐突
- #190 InteractionProcessSnapshot
- #191 Interaction Process Appraisal
- #192 Expression Appraisal統合
- #193 Discourse Appraisal
- #194 Turn-taking最終統合/実画面検証

## Awakening
- #186 Parent
- #196 Context/Persistence
- #197 Appraisal/Lifecycle
- #198 Expression/Autonomous Interaction
- #199 Final HTTP/SSE/実画面Verification

## Body / Avatar
- #211 Generative Body Motion
- #213 発音/Viseme同期口形
- #214 Character Profile由来Body Expression Style
- #215 Body Pose Lab簡素化
- #221 Body output未接続時graceful shutdown

## Input/触覚・GUI・Memory
- #217 連続接触意味区間
- #187 GUI全画面最新化Parent
- #295 Issue親子/依存/進行ノードグラフ
- #201 Memoryパイプライン最適化

## 2026-08-12時点の重要Openテーマ
1. Characterを意味決定から切り離してLanguage Realizerへ限定する。
2. SemanticUtterancePlanを「何を言うか」の正本へする。
3. Realization後の意味保持をtyped semanticsで検証する。
4. 有限自然語辞書/regex semantic decisionを全廃する。
5. 軽量モデルでも安定する契約へ再設計する。
6. BodyをGenerative Motionへ統合する。
7. Character Bibleを作り、Language/Voice/Bodyへ一貫した「ゆららしさ」を投影する。
8. Memory最適化・GUI横断更新は高優先Issueの後段で進める。

---

# Part VI. チャット削除後の復帰手順

1. 本書を読む。
2. Issue #207を読む。
3. GitHub Project「プロジェクトゆら」を工程順に確認する。
4. In progress / Verification / Blocked / Readyを確認する。
5. 対象Issue本文・最新コメントを読む。
6. 対応PRの最新状態を確認する。
7. 必要なときだけ対象branch差分を確認する。

「なぜこの方式？」は本書→該当Issue→docs/設計書。「今どこまで？」はProjectを正本とする。古branchは#208監査方針に従い、外部Render参照やVerification branchをGit ancestryだけで削除しない。同じ修正を別Issueへ重複させない。実装開始前に親Issue・対象Issue・最新設計書・方針不一致PRを確認し、設計→実装の順を守る。

---

# Appendix A. プロジェクト内チャット索引

| 日付 | チャット名 | 主題 |
|---|---|---|
| 2026-07-26 | AI Liver ゆら GitHub Wiki構成・運用設計 | Wiki/永続ドキュメント運用 |
| 2026-08-03 | 入力意味解析LLM・内部司令LLM分離実装 | LLM責務分離 |
| 2026-08-03 | 内部指示器ラボのブラウザ検証環境構築 | Render検証Lab |
| 2026-08-03〜04 | 内部指示器ラボ・InternalDirective検証 | Internal Directive評価 |
| 2026-08-04 | アバター自由動作設計・Body制御方式の再構築 | Generative Body Motion |
| 2026-08-06 | 会話挙動改善・記憶最適化とIssue整理 | 会話/GUI/Memory/Issue |
| 2026-08-06 | GitHub Projects「プロジェクトゆら」運用設計 | Projects v2 |
| 2026-08-08 | GitHub Projects v2 運用ルール・基準情報管理 | Snapshot/Status/工程 |
| 2026-08-08 | 作業進捗と動作設計 | Body実画面検証 |
| 2026-08-09 | チャット名再設定提案 | 索引性改善 |
| 2026-08-11 | Issue親子関係可視化 | Issue graph GUI |
| 2026-08-12 | システム視覚化ツール | System/module graph |

# Appendix B. 設計判断の変遷

```text
入力理解:
表面語/個別matcher
→ LLMでStructuredInputMeaning
→ Input Meaningをsemantic authorityへ一本化

発話生成:
Character LLMが意味・キャラ・音声まで担当
→ Input Meaning / Internal Directive分離
→ SemanticUtterancePlan / Character Realizer / SpeechPerformancePlan分離

Body:
固定Gesture/Pose
→ 高レベルBody指示
→ Skeleton/IK/KinematicsによるGenerative Motion

発話前表現:
固定considering/pre-speech animation
→ 却下
→ Runtime事実→Appraisal→Expressionの因果表現

Memory:
会話保存中心
→ Topic/Agent/Relationship等へ分化
→ Memory Candidate/Router/Consolidation最適化

プロジェクト管理:
チャット中心
→ branch/PR中心
→ Issue + Projects v2 + docs + Verificationを正本化
→ #207 + 本書で引き継ぎを永続化
```

# Appendix C. 更新ルール

次の場合に本書を更新する。
- 新しい長期設計原則が確定した。
- 大きな方針を撤回/置換した。
- 新しいParent Issueが作られた。
- プロジェクト内の重要チャットが終了した。
- 大規模Verificationで設計前提が覆った。
- 全体アーキテクチャの責務境界が変わった。

古い記述を単純削除せず、「当時の判断」と「現在の正規設計」を区別して残す。
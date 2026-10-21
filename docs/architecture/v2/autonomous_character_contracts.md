# 統合本体：自律人格・行動・発話の製品契約

状態: 正本補足（設計のみ）。基準: [統合本体アーキテクチャ](unified_core_architecture.md)。
範囲: 人格・内部状態・自律判断・発話・身体・記憶・起動と受入れ。実装済み・試験合格を意味しない。
詳細: [内部状態の時間関数・判断入力契約](internal_state_trajectory_contracts.md)。

## 1. 完成体の意味

- 製品は外部プロンプトを待つ応答器ではなく、内部状態・記憶・Goal・状況・注意から自律的に思考、判断、発話、沈黙、活動を選べる継続主体である。
- 正規起動は `python -m app` の単一の製品構成とする。段階・縮小構成の起動を別製品や完成条件にしない。
- 「Core」はTTS、画面、描画器、実機などが未配備でも成り立つ本体の**全論理責務**であり、一部の脳だけを実行する省略モードではない。
- 同じ実行Identity・Composition Rootの下に、Input、Meaning、Appraisal/Internal State、Attention、Executive、Goal/Commitment、Activity、Memory/Reflection、Speech意味計画/Character言語化/検証、Body意図・連続制御、Runtime/Lifecycleを登録する。必須Owner・Portの欠落は起動失敗。任意Provider不在は型付き利用不可とし、論理Ownerを削除しない。
- 設計と製品はPython **3.10.5** を前提とし、Domain→外部の依存を禁止するClean Architectureの依存方向を守る。構成は `app/bootstrap/`、抽象Portは内側、Adapter/Infrastructureは外側が所有する。
- 製品のコード、設計書、ファイル名、テスト名、公開識別子に人物固有名や旧工程短縮ラベルを埋め込まない。人物固有の表示名・人物像・声・外観などは変更可能なCharacter Definition/設定の**値**にのみ置く。既存文書の履歴表記を新しい識別子へ再利用しない。既存資産の全面改名は別のコード／配置移行であり、本書追加だけで完了とはしない。

## 2. 七層人格と九系統の現在状態

人格の理論的背景は既存の心理構造資料に記されたRothbart/Ahadi (1994)、Mischel/Shoda (1995)、McAdams/Pals (2006)、Fleeson/Jayawickreme (2015)を**参考枠**として採用する。AI心理の実証済み法則とみなさない。

| 層 | 人格構造 | Authority |
| --- | --- | --- |
| 1 | 本質的傾向 | 比較的安定した人物設定 |
| 2 | Deep Prior | 設定由来の深層傾向。生物学的事実とLoreを区別 |
| 3 | 形成経験・バックボーン | 人物設定の形成史。実際の観測経験とは別 |
| 4 | 信念・価値観 | 比較的安定した意味・評価傾向 |
| 5 | 自己モデル・物語的自己 | 自己理解。未確認の実行能力を捏造しない |
| 6 | 特徴的な適応傾向 | 場面に応じた反応可能性。固定反応ではない |
| 7 | 現在状態・Situation・意味づけ | Runtimeの各正規Ownerが保持する動的事実 |

層1〜6はCharacter Definitionから読み取り専用に投影し、層7を静的Profileへコピーしない。形成根拠参照は説明可能性を担保するが、機械的な行動決定規則ではない。

内部状態の9系統は Emotion、Desire、Drive、Motivation、Value/Moral appraisal、Interest/Curiosity、Relationship、Energy、Arousal。対象付きInterest/Relationship、cause・confidence・revision・updated_at・出典等は[Appraisal/Internal State](appraisal_internal_state_contracts.md)の型付き契約を保持する。

- Appraisalは出来事・現在状態・Goal・Relationship・Memoryなどを評価して候補を生成し、Reducerのみが現在状態を確定する。
- 状態の数値は時点の観測/確定値であり、心理状態の全情報ではない。確定した基準点・原因・時間的推移の**関数投影**は[時間関数契約](internal_state_trajectory_contracts.md)で定める。
- Emotion→特定のセリフ、Fear→逃走、喜び→必ず発話、といった一対一の定型対応を禁止する。安全・権限判定をValue/Moral stateへ委譲しない。
- 記憶の過去感情は現在状態ではなく、人物設定の安定した特性は現在感情の捏造根拠にはならない。

## 3. 内部契機からの自律判断

- user inputなしでも Internal Stateの確定変化、Memoryの関連性、Goal/Commitment、Activity結果、観測事実、Lifecycleなどを正規のtyped sourceとしてAttentionへ通知し、Executive判断を開始できる。実行主体は入力待ちで停止しない。
- time tickを使うこと自体は禁止しないが、一定秒数ごとのテキスト生成や発言義務を設定してはならない。新しい状態・関連性・Goalがなければ無発話が継続してよい。
- Executiveは入力を必ず応答へ変換せず、respond / act / wait / ignore / defer / refuse / silence / continue_activity等を、人格・状態の時間文脈・Memory・Focus・Situation・能力を根拠に選ぶ。
- 数値・時間関数から閾値をif文で評価して発言、沈黙、身体行動を確定する別の意思決定器を設けない。Executive LLMの意味判断を唯一のGoal/Action authorityとし、LLM候補も通常のcommit gateで確定する。
- 主観評価・Attentionによるtrigger適格性・Goal store・Executive判断を混同しない。Attentionは順番/割込可否、Executiveは意思決定、Speech Semanticsは「何を話すか」、Character Languageは「どう言うか」を各々所有する。
- 発言しなかった場合にも、入力・注意・必要な記憶・沈黙の判断根拠を正規契約に従い扱う。沈黙は失敗や未処理ではない。

## 4. 発話・沈黙・身体と非直列実行

- 発言意図を確定した場合、Speech Semantics→Character Language→検証→Performance/TTS/Presentationの各責務を維持する。実際に提示された範囲だけを提示済み事実として記録する。音声出力がない場合も意味生成Ownerを削除しない。
- **発話Aの再生終了を、次のAppraisal/Executive/Speech B準備開始の条件にしない。** independent lane/queueにより先行準備し、旧候補の取消、現在性再検証、interrupt/fairness/backpressureを行う。
- 会話が盛り上がり、次の発言が必要と判断され、出力準備が間に合う環境では、発話Aの終了から発話Bの開始まで**1秒未満**を実現する。固定の発話間隔を設定する要件ではなく、実測で判定する。
- 発話意欲が低い等の文脈では、長時間または継続的な沈黙を選べる。連続発話と沈黙を二つの固定モードにはしない。
- Speech/BodyはExecutiveからの兄弟経路であり、Character言語化の完了がBody意図の開始条件とは限らない。Bodyは意図・表現傾向・物理制約から連続動作を生成し、装置不在を実動作成功へ読み替えない。
- LLM、TTS、描画、Body、DB、Reflectionの待機は無関係な認知を止めない。資源上限はbounded queueで管理し、global async lock/serial loopでLLM全体を待たない。古い候補はOwnerごとのrevision/generationで拒否する。
- すべてのLLMで実際に1秒以内の応答を保証するという意味ではない。資源不足と内部の直列待ちを区別し、遅延を計測可能にする。

## 5. 記憶・Character構成・起動

- Memoryは保存された事実とprovenanceを提供し、Reflectionは信頼済みの実行結果等から保存候補を提案する。存在しない経験、発話成功、保存成功を捏造しない。
- Character表示名・本質・Deep Prior・形成史・価値観・自己モデル・適応傾向・言語/音声/身体スタイルは設定で差し替え可能とし、本体のDomain/UseCase/Runtimeコードを変更しない。Character Profileは層7の現在状態を所有しない。
- Core、人物、認知Role、Speech/Body、Memory等を同じ設定rootで検証し、同一runの正規Ownerへ明示接続する。未設定外部Providerと未登録必須Ownerを区別する。
- 初期化/再起動/復元は各Ownerのrestart-safe契約で扱う。過去のEmotion記憶を現在状態へ直接注入せず、関数の保存データを無条件に正規現在値として扱わない。
- shutdownは新規受付停止→取消/回収→正規の保存対象だけをbounded flush→依存順の終了。所有していない資源は閉じない。

## 6. 受入と試験方針

製品のpytest collection全体は**1,000ケース以内**（unit / contract / integration / systemの合計）とする。重複・旧仕様を統合して減らす。skip/xfailや未実装分の削除で件数のみ合わせない。CIにはcollection件数のgateと必要なscenario coverageを置く。現行suiteが合格したことの宣言ではない。

- 必須Ownerのある標準起動、外部提供先なしでの本体継続、内部契機からの自律活動、入力ごとの応答/非応答選択。
- 固定間隔による発言強制なし、話したい文脈での次発話並行準備と1秒未満の**準備可能条件下**実測、沈黙時にも認知管理継続。
- 七層・九系統の正しい分離、関数による同一入力/時刻の再現性、原因・推移・現在性・Reducerのみの確定、未根拠値の非捏造。
- Speech意味とCharacter表現の分離、raw内部状態値をCharacter LLMへ直送しない、Body指令と実行事実の分離、Memoryの出典。
- 設定差替えによる人物可変化、製品コード/文書/ファイル名の中立命名、Python 3.10.5、Clean Architecture、DB復旧/終了・所有権、資源遅延中の並行性。
- **新方式と旧方式の改善率・A/B比較は行わない。** 正規の機能・境界・再現性試験は必要である。

具体的な既存UCへの紐付けと未受入状態は[受入対応表](unified_core_acceptance_matrix.md)に従う。本書は製品コードの採用・実環境PASSを宣言しない。

## 7. 正本と未確定の境界

- 関数方式の採用、現行減衰規則の維持、入力の時間文脈、LLMによる意思判断、固定発話閾値・定期発話の禁止は確定方針。
- **未定義の各facetの減衰関数、個体基準値の算出法、LLM入力の追加容量、時間経過の有効期間、保存履歴圧縮の方針・頻度は未確定**。根拠なく具体値を設定しない。
- 関数方式の追加はAppraisal、Executive、Persistence、Speechにおける既存のOwner、Role、schema/version、revision、fenceを回避しない。
- 既存の人物固有名や旧工程識別子の横断移行と現在のコードの未接続部分は、設計の採用と区別して追跡する。

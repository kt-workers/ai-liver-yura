# Character / Response Validator Cloud Validation Lab v1.0.0

## 目的

Character生成とResponse Validatorを`python -m app`の全体Runtimeから切り離し、productionのCharacter/Validator経路を実LLMで反復検証できるようにする。

本LabはIssue #223の再利用可能な検証基盤であり、Issue #210の内部状態回答品質を最初の実用ケースとする。

## 位置付け

検証レベルは次のうち1〜2を担当する。

```text
1. モジュール単体検証
2. 隣接モジュール契約検証
3. サブシステム結合試験
4. 全体結合 / System Verification
```

Body / TTS / Avatar / DB / Runtime lifecycleを起動しない。

## branch方針

- branch: `test/character-response-cloud-validation`
- source: PR #219 `fix/internal-state-natural-self-expression` の最新HEAD
- Draft PR base: `fix/internal-state-natural-self-expression`

検証UIを`develop`へ直接混在させず、#210の最新Character/Validator実装をそのまま評価するstacked validation branchとする。

## production境界

Lab専用のCharacter生成・Validator判定ロジックは作らない。

```text
Lab request
→ production domain contractへ変換
→ ResponseContextBuilder
→ CharacterLlmService
→ ResponseValidator
→ CharacterResponsePipeline
→ Lab result projection
```

使用するproduction要素:

- `ResponseContextBuilder`
- `CharacterLlmService`
- `ResponseValidator`
- `CharacterResponsePipeline`
- `CharacterPromptBuilder`
- `ResponseValidatorPromptBuilder`
- `OpenAIResponseGenerator`
- `ResponseGeneratorRoleAdapter`

## 入力

最低限、次を型付きJSONとして受ける。

- user input
- StructuredInputMeaning
- Validated Internal Directive相当のdirective
- Emotion
- Drive
- Memory / related knowledge
- recent speech
- recent conversation
- recent topic
- response constraints
- Character Profile

Labはproduction DTO/Enumへ変換し、独自の意味解釈を行わない。

## 出力

- 最終Character response
- Character generation result
- accepted / rejectedを含む最終状態
- typed target
- Emotion / Drive
- recent speech等の入力snapshot
- 実行時間
- stop stage

production Pipelineの内部Traceは既存TraceLoggerを正本とする。Lab側は独自Validator理由を推測しない。

## live / fake

### live

OpenAI Adapterを使用してproduction prompt経路を実行する。

環境変数:

- `YURA_CHARACTER_RESPONSE_LAB_MODE=live`
- `YURA_CHARACTER_RESPONSE_LAB_MODEL=<model>`
- `YURA_CHARACTER_RESPONSE_LAB_VALIDATOR_MODEL=<model>`（省略時は同じmodel）
- `OPENAI_API_KEY`
- `YURA_LAB_USERNAME`
- `YURA_LAB_PASSWORD`

### fake

HTTP/API/UI/production pipeline wiringの自動テスト用。固定回答の品質評価には使わない。

## #210用プリセット

少なくとも以下を持つ。

1. `joy_low_curiosity_high`
   - target=`internal_state/joy`
   - joy/amusement低、curiosity/engagement高
2. `current_feeling_repeat`
   - current feeling直接質問
   - recent speechあり
3. `anger_low`
4. `current_desire`

プリセットは回答テンプレートではなく入力条件再現用。

## Export

画面上の入力と結果をJSONとしてコピー可能にする。API key等のsecretは含めない。

## 非目標

- #210の修正そのもの
- Internal Directive Plannerの再実装
- Memory Retrieval/Rankingの再実装
- Body/TTS/Avatar統合
- fixed phrase / 言い換え辞書
- Lab独自のresponse validator

## 完了条件

- production Character/Validator pipelineを全体Runtimeなしで実行できる
- fake modeで自動テスト可能
- live modeでOpenAI接続可能
- #210用プリセットを再現できる
- Body/TTS/Avatar/DB未接続で動作する
- Basic認証を維持する
- health endpointでstop stageと設定状態を確認できる
- Lab API/UIテストがある

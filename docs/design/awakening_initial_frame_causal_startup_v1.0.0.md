# Awakening初期Frame因果起動設計 v1.0.0

## 目的

Issue #198 / Parent #186 の完了条件である「初期Frameから評価済みEmotionとAwakening状態が反映される」を、固定起床PresetやBody専用コマンドを追加せずに満たす。

## 検出した競合

現状の通常起動は次の順序になっている。

```text
Runtime生成
→ Body Runtime生成
→ Body Runtime start
→ AwakeningContext生成
→ Runtime task start
→ APP_STARTED publish
→ Event Queue
→ AgentLifeServiceでAwakening Appraisal / State更新
```

Body Runtimeはstart直後からtickし、各tickでBody causal storeの最新Emotion / Awakening Affectを読む。一方、Body causal storeはAgentState observerから更新されるため、`APP_STARTED`がRuntimeで処理される前は既定のneutral Emotion / empty Awakening Affectを保持している。

そのため、Event Queueの処理よりBodyの最初のtickが先に走ると、外部へ公開される最初のBodyPoseFrameが固定neutralになる。

## 設計方針

起動Contextを評価する因果ロジックをBody側へ複製しない。`AgentEventStateUpdater`が使用する既存の`AwakeningStateTransitionService`を、Body Runtimeをstartする前の初期因果Snapshot作成にも再利用する。

```text
Runtime生成
→ Body Runtime生成（まだstartしない）
→ AwakeningContext生成
→ APP_STARTEDを1つ生成
→ AwakeningStateTransitionServiceで同Eventを先行評価
→ Body causal storeへ projected Emotion / Awakening Affect をseed
→ Body Runtime start
→ 最初のtickでseed済みProviderを読む
→ Runtime task start
→ 同じAPP_STARTEDを通常Pipelineへpublish
→ AgentStateへ正式反映
```

Body Runtimeの`tick_once()`はFrame公開前に毎回Providerを読み直して`BodyExpressionInput`を更新する。そのためController構築時の互換neutral初期値は外部Frameとして公開されず、start前にseedされた覚醒因果状態が最初の公開Frameへ使われる。

## 一貫性

先行seedとRuntime正式更新は、同じ`APP_STARTED` payload・同じ起動前AgentState・同じ`AwakeningStateTransitionService`を使用する。

先行seedで保持するのはBodyが必要とする有限状態だけとする。

- projected Emotion
- projected AwakeningStateから導出した`BodyAwakeningAffect`

Desire / Drive / Moral / Relationship / Memory等の正式なAgentState更新は従来どおりRuntime Pipelineが所有する。Body側でAgentStateを独自更新しない。

## Body unavailable時

Body Runtimeが存在しない場合はseed処理を行わない。`APP_STARTED`は従来どおりRuntimeへ流れ、Awakening Appraisal / Emotion / Desire / Drive / LifecycleはBodyの有無に依存せず更新される。

## Persistence障害時

AwakeningContextServiceの既存仕様に従い、Snapshot欠損・破損・version mismatch・I/O failureはcold start Contextへ安全に縮退する。Body初期FrameのためにPersistenceを必須化しない。

## 非目標

以下は導入しない。

- 固定の「おはよう」発話
- 起床・あくび・伸び等の固定Motion preset
- `drowsy → yawn`等の1対1マッピング
- Body Controller内でのAwakening Appraisal
- Raw User Text / Prompt / Character本文のBodyへの転送
- Body独自のEmotion / Desire / Drive更新

## 診断

先行seed時は本文を含まない有限値だけをTraceへ記録する。

- startup kind
- awakening lifecycle phase
- body awakening salience
- projected emotion mood / arousal / valence / talkativeness

Raw Prompt、User Text、Character本文、Memory本文は記録しない。

## 回帰テスト

1. Body startup seedと通常`AgentEventStateUpdater`のAwakening projectionが一致する。
2. APP_STARTED以外をstartup seedへ渡した場合は拒否する。
3. AwakeningContextがないAPP_STARTEDはseedせず安全に戻る。
4. seed後のBody Runtime最初の`tick_once()`がneutral既定値ではなくseed済みEmotion / Awakening Affectを使用する。
5. Body unavailableでもAPP_STARTEDの通常Runtime更新を阻害しない。
6. 全体pytestを実行する。

## Verification

#198は実際に見えるBody表現を変更するため、CI成功後もDraftを維持してVerificationへ移す。

最終的な実HTTP / SSE / Body Pose Labでの起動Lifecycle確認は後続Issue #199で行う。#203 / #204が未統合のため、PR #205は依存PRより先にマージしない。

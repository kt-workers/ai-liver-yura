# 会話セリフ品質：低主体性挨拶の発話制約 v1.0.0

## 1. 背景

実プロセス評価で、ユーザーの単純な挨拶に対してSituation Evaluatorが次を確定していた。

```text
speech_act=greeting
conversation_phase=greeting
initiative_level=0.15
```

最初のCharacter応答は質問を含んだためValidatorに拒否されたが、再生成後は質問を除く代わりに、最近気になるゲームという新しい話題を開始した。

```text
こんにちは！今日も元気にいこうね。最近、面白そうなゲームが気になってるんだ。
```

## 2. 原因

Response Content PlanはDesire・Motivation・Moralから先に生成されるため、通常会話の個別の`speech_act`、`conversation_phase`、`initiative_level`を直接反映していなかった。

また、`observation_only`は「会話を広げない」という意味ではない。Activity選択・実行許可・事実認定へResponse Content Planを使用しないための安全属性である。

したがって問題は`observation_only`とBudgetの論理矛盾ではなく、Character境界で確定済みの対話方針による最終縮退がなかったことにある。

## 3. 修正契約

Response Content Planの元データは変更せず、Character Prompt生成直前に実効Planを作る。

### 3.1 低主体性の挨拶

次をすべて満たす場合を対象とする。

```text
initiative_level <= 0.25
speech_act == greeting または conversation_phase == greeting
```

実効Planを次へ縮退する。

- `question_budget=0`
- `new_direction_budget=0`
- `self_disclosure_level=none`
- 質問戦略を除外
- 新話題展開戦略を除外
- 自己開示戦略を除外
- `acknowledge_other`を最低1件保持

Character Promptへ次も明示する。

- 挨拶への短い返礼だけに留める
- 質問しない
- 自己開示しない
- 新しい話題を始めない
- 最近の関心や好みを持ち出さない
- 原則1文、長くても2文

### 3.2 その他の低主体性応答

`initiative_level <= 0.25`では、質問戦略と新方向戦略を除外し、両Budgetを0にする。

## 4. 保持する境界

- Situation Evaluatorの確定結果を変更しない
- Activity選択を変更しない
- Desire・Motivation・Moralの更新式を変更しない
- 通常主体性の会話Planを変更しない
- 接触反応を変更しない
- セリフの一般的な反復・語彙・質問頻度の全体改善は別工程とする

## 5. 回帰テスト

次を固定する。

1. 低主体性挨拶では質問・新話題・自己開示が無効になる
2. 通常主体性では元のPlanを維持する
3. 挨拶以外の低主体性応答でも質問・新方向を無効にする
4. Character Promptへ縮退後のPlanと明示制約が出力される

## 6. 次の評価

同じ「こんにちは」を実プロセスへ入力し、次を確認する。

- 応答が短い挨拶に留まる
- 新しいゲーム等の話題を開始しない
- 質問しない
- 2回目生成が必要な場合も同じ制約を維持する

その後、挨拶以外の会話について、直接回答性、意味的反復、質問頻度、話題展開を個別に評価する。

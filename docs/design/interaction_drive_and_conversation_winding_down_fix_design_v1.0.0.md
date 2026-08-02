# 画面操作Driveと会話終了判定 修正設計 v1.0.0

## 1. 目的

実画面からの接触操作と通常会話を組み合わせた長時間動作ログで確認された、次の評価阻害要因を修正する。

1. 一つのドラッグ操作を構成する多数の座標サンプルが、それぞれ独立したDrive刺激として加算される
2. 「今日はそろそろ終わりにしようか」のような会話終了表現が、語尾だけを根拠に未対応Activityの実行要求へ分類される

## 2. 実動作で確認した事実

### 2.1 評価対象プロセス

対象プロセスは2026-08-02 03:00:10 JSTに起動し、09:59:39 JSTまで動作した。

Core発話確定境界の最終修正コミットは同日04:48:50 JSTに作成されているため、03:06から03:11頃に記録された自律発話の連続出力は、最終修正前から起動していた旧プロセスの結果である。この部分だけは最新HEADの自律発話間隔・話題終了判定の検証結果として扱わない。

一方、画面操作のサンプル単位Drive更新と会話終了文の決定論的分類は、ログ取得後に最新HEADのコードへ照合しても残っていたため、本修正の対象とした。

### 2.2 画面操作

対象ログには236件の`USER_INTERACTION`が含まれていた。

- drag: 216件
- tap: 11件
- double_tap: 9件
- gesture_id: 20種類

発話反応は227件が既存のReaction Policyで抑制されていたため、画面操作ごとの発話連打は防止できていた。

一方、Drive更新はドラッグの`start / update / end`を区別せず、各サンプルへ固定刺激を加えていた。座標追跡用の`update`が意味上の新しい接触ではないにもかかわらず、Curiosity・Engagement・Boredom・Energyへ毎回反映され、Energyが0へ到達した。

感情評価は接触時間・接触履歴・境界要求を扱う別責務であり、本修正では変更しない。Driveだけをジェスチャー単位の注意刺激へ近づける。

### 2.3 会話終了表現

「今日はそろそろ終わりにしようか」はSituation LLMの意味解析失敗時、決定論的な補助判定で語尾`しようか`に一致し、`execution_request_without_matching_activity`へ分類された。

これは「会話を終える」という対話フェーズと、Plugin Activityを開始・停止する実行要求を混同している。

「またあした」はSituation LLM経路では通常会話かつ`conversation_phase=winding_down`として扱われていた。今回の修正は、LLMが失敗した場合の決定論的Fallbackも同じ意味へ揃えるものである。

## 3. 画面操作Drive契約

単発操作の既存契約は維持する。

- tap
- double_tap
- long_press
- phaseを持たない旧形式のdrag

`contact_phase`または`gesture_phase`を持つ連続接触は、次の係数でDriveへ反映する。

| phase | stimulus_scale | 意味 |
|---|---:|---|
| start | 0.35 | 接触開始による注意喚起 |
| update | 0.00 | 座標追跡サンプル。新規刺激にしない |
| end | 0.15 | 接触終了の弱い変化 |
| phase不明かつ`continuous_contact=true` | 0.25 | 互換入力向けの保守的刺激 |

phaseと`continuous_contact`を持たない旧形式のdragは、一回の完結した操作として`stimulus_scale=1.0`を維持する。これにより、既存Simulatorや旧クライアントの契約を壊さず、現行Web画面から送られる連続座標サンプルだけを抑制する。

Drive変化は既存の単発操作量へ係数を掛ける。

```text
curiosity += 0.03 * scale
engagement += 0.08 * scale
boredom -= 0.08 * scale
energy -= 0.01 * scale
```

これにより、一つのドラッグに含まれるサンプル数やブラウザ描画頻度が内的状態を左右しない。

Traceへ次を追加する。

- `interaction_kind`
- `contact_phase`
- `stimulus_scale`

## 4. 会話終了判定契約

一般的な実行要求の語尾判定より先に、会話終了・別れの定型表現を判定する。

対象例:

- 今日はそろそろ終わりにしようか
- 今日はここまでにしよう
- また明日
- ばいばい
- おやすみ

これらは`UserRequestKind.CHAT`、reason=`conversation_winding_down`とする。

一方、対象Activityを明示した「エコー活動を終わりにしよう」などは、従来どおり実行要求として扱う。会話終了表現の追加によってPlugin Activityの開始・停止要求を奪わない。

## 5. 受入条件

1. 単発tapと旧形式dragの既存Drive変化を維持する
2. 連続ドラッグの`update`を何十件処理してもDriveが変化しない
3. dragの開始・終了は一つのジェスチャーとして弱くDriveへ反映される
4. 画面のサンプリング頻度だけでEnergyが0へ到達しない
5. 「今日はそろそろ終わりにしようか」が通常会話へ流れる
6. 同文が`execution_request_without_matching_activity`にならない
7. Activityを明示した停止要求は実行要求のまま維持される
8. 既存の感情評価・Reaction Policy・Plugin Activity境界を変更しない

## 6. 回帰テスト

GitHub Actionsで次を確認した。

```text
1587 passed
1 warning
47.39 seconds
```

実行コマンドは`pytest -x -vv`である。Ruff、mypy、Blackは依存として導入されるが、このWorkflowでは実行されていない。

追加した主な回帰:

- 80件のdrag updateでもDriveが飽和しない
- `continuous_contact`省略時もphase=`update`ならDriveへ加算しない
- 単発tapとphaseなしdragの既存挙動を維持する
- 会話終了文が未対応Activity実行要求にならない
- Activityを明示した停止要求は実行要求として残る

## 7. 再評価条件

最新HEADで実プロセスを新しく起動し、次を確認する。

1. 数秒間のドラッグを複数回行う
2. Traceで`drag_update / stimulus_scale=0.0`を確認する
3. Energyが座標サンプル数に比例して低下しないことを確認する
4. 「今日はそろそろ終わりにしようか」と入力する
5. Behavior Planが通常会話として成立し、未対応Activity拒否にならないことを確認する
6. その後入力せず放置し、自律発話間隔と話題終了判定を確認する

修正前から起動し続けているプロセスは新しいコードを読み込まないため、必ず最新HEADで再起動したプロセスを評価する。

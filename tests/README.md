# テストスイート運用方針

## 目的

テスト件数を減らすこと自体を目的にせず、検証責任を維持したまま、PRごとのフィードバック時間を短縮します。

## 分類

- `unit`: 外部I/O、実時間待機、常駐スレッドを伴わない高速な単体テスト
- `integration`: 複数コンポーネント間の接続を検証する統合テスト
- `slow`: 実時間待機、スレッド待機、長時間処理を伴うテスト
- `external`: DB、HTTP、外部サービスなど実環境依存を伴うテスト

## 基本方針

1. 単体テストでは `time.sleep()` と `asyncio.sleep()` を使用しない。
2. 時刻や待機はClock、Event、Queue、注入可能なsleep関数で制御する。
3. スレッドの起動・停止を検証するテストは代表ケースに限定する。
4. 同じ振る舞いを単体テストと統合テストの両方で詳細検証しない。
5. 外部サービスは通常のPRテストではFakeまたはMockに置き換える。
6. 旧仕様互換テストには、維持理由と廃止条件を明記する。

## 想定する実行単位

### PR向け高速テスト

```bash
pytest -m "not slow and not external" -x
```

### 統合テスト

```bash
pytest -m integration
```

### 低速・外部依存テスト

```bash
pytest -m "slow or external"
```

### 完全回帰テスト

```bash
pytest
```

マーカー付与が完了するまでは、上記コマンドを正式なCIゲートには使用しません。

## 監査

静的な待機・外部I/O候補は次で確認します。

```bash
python scripts/test_suite_audit.py
```

実行時間はカテゴリまたはファイル単位で次のように測定します。

```bash
pytest <対象> --durations=50 --durations-min=0.1
```

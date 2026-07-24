# 依存方向テスト再確認

## 結論

現行`develop`には、Python ASTを利用した依存方向テストが既に存在する。

対象ファイル:

```text
tests/test_architecture_boundaries.py
```

そのため、現行アーキテクチャ監査の「依存方向テストは未対応」という判定は誤りであり、工程2「依存方向テストの追加」は対応済みとして扱う。

## 実装済みの主な境界

- Coreから具象Pluginへの依存禁止
- `app/__main__.py`でのOBS、YouTube、Streaming Admin直接Composition禁止
- Shared ContractからCore、Domain、Runtime、Plugin、Adapterへの依存禁止
- DomainからAdapter、Plugin、Framework、外部I/Oライブラリへの依存禁止
- Usecaseから具象Adapterへの依存禁止
- Admin APIとStreaming Plugin内部実装の分離
- YouTube Streaming PluginとCore内部モデルの分離
- Runtime CoordinatorへのStreaming固有分岐混入防止
- Runtimeから具象Adapter、Pluginへの依存禁止
- Games Plugin、Voice Output Plugin、LLM Provider Plugin、Memory Pluginの境界保護
- TTS境界とEmotion Stateの分離

## 評価

既存テストは単なる件数ベースラインではなく、禁止依存を明示して失敗させる方式になっている。現状の主要境界は既にテストで固定されているため、同等テストの重複追加は行わない。

## 残る課題

依存方向テストそのものの追加ではなく、今後の構造変更に合わせて次を段階的に拡張する。

- `app/ports`全体の依存方向規則
- `app/config`の機能別分割後の境界
- Composer分割後のBootstrap間依存
- Topicロジック分離後のRuntime境界
- Adapter間の循環依存検出

## 実施順序への反映

工程2は対応済みとして完了し、次は工程3へ進む。

```text
話題選択ロジックの分離
```

最初の分離では挙動を変更せず、`AgentLifeService`内部の話題状態生成、指標計算、継続終了判定を専用コンポーネントへ移す。

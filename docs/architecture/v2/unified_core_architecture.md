# AI Liver ゆら — 統合本体アーキテクチャ

状態: 正本 / 2026-10-17改訂。旧「Minimum Core」「S2 Production」の製品構成契約に優先する。
対象: ゆら本体。Python 3.10.5（`>=3.10,<3.11`）。旧機能を縮小した代替構成を製品として実装しない。

## 1. 目標と唯一の本体

`python -m app` は、完成形のゆらを構成する唯一の標準CLI入口である。入力意味解析だけを起動する経路、S2専用モード、機能数を減らした「仮のゆら」を本番起動や完成条件にしない。テスト時にPortを置換しても登録されるDomainの責務や構成を縮小しない。

本体は同一の実行Identityとライフサイクルのもとで、入力・内部契機、意味解析、主観評価、感情・欲求・内部状態、注意、自律判断、目標・計画、活動・実行事実、記憶・振り返り、発話の意味・言語化、身体への意図、並行処理・終了を連結する。これらの機能を不要扱いにして起動成功へ読み替えない。

GUI、配信画面、ゲーム技能、個別の音声エンジン、アバター描画器は交換可能な外部提供先であり、ゆらの意思決定のOwnerにはならない。外部能力が未提供のときは、当該能力の可用性を事実どおり報告し、命令や実行成功を補作しない。

## 2. フォルダと責務

| 配置 | 唯一の責務 |
| --- | --- |
| `app/domain/` | 感情・欲求・目標・判断・意味・実行事実のモデル、状態遷移、不変条件、純粋な規則 |
| `app/usecases/` | 複数Domain OwnerとPortを協調し、一連の認知・活動・終了を実行する |
| `app/runtime/` | queue・lane・時刻・取消・並列タスク・backpressureの機構 |
| `app/usecases/ports/` / Domain contracts | 外部提供先への抽象契約 |
| `app/adapters/` | LLM・音声・人物ファイルなどの入出力・Provider変換 |
| `app/infrastructure/` | DB・時計・接続・資源・外部プロセス等の具体実装 |
| `app/config/` | 本番設定の型付き読込み・厳格検証。意思決定ルールを持たない |
| `app/bootstrap/` | 唯一のComposition Rootで具象を組立て、所有・終了を接続する |
| `app/application.py` / `app/__main__.py` | 利用者向け起動・停止入口だけ |

DomainはUseCase・Adapter・Infrastructure・Bootstrapをimportしない。UseCaseは具象Adapter/Infrastructureを直接生成しない。Bootstrapに構成コードを集約し、`composition/` に追加の起動rootを作らない。責務の移設時は利用側import・テストも同時に修正する。

**再構築時の移設単位:** ファイルを丸ごと別フォルダへ移しただけでは責務分離の完了としない。関数・クラスごとに責務と依存方向を確認し、正規の定義場所へ移す。参照元、公開Port、起動・終了処理を同時に整理し、同じOwnerや処理を複製しない。旧入口の再公開は必要な互換範囲に限る。

## 3. 唯一の構成・起動・停止

1. `config/core.yaml` と参照する各Ownerの設定・人物定義を検査する。Python 3.10.5の依存とschema revisionを固定する。
2. 実行Identityを一度だけ発行し、Goal、Activity、Internal State、Attention、Memory、Brain Runtime等の正規Ownerを構築する。同じ状態を別の段階用に複製しない。
3. Input Meaning、Appraisal、Executive、Attention、Goal/Activity、記憶、Speechの本体機能をPort経由で明示接続する。必須Ownerの未構成、未登録、設定不整合は起動失敗として返す。
4. 具体的Providerと外部能力の可用性を確認する。任意提供先の不在は当該能力の型付きUnavailableであり、Brainモジュールを省く理由にはしない。
5. 全Ownerを公開した後に受付を開始する。受付後も内部契機は入力待ちへ直列化せず、実際の状態と実行結果を観測し続ける。
6. 停止時は新規受付を閉じ、活動・音声・実行中のタスク・保存を整合させ、所有する資源を逆順に解放する。借用した接続は閉じない。

起動失敗をより小さい構成へfallbackさせない。起動成功は必須Ownerの準備完了を意味するが、未実行の発話・認知結果や外部I/O成功を意味しない。

## 4. 永続化・発話・身体

Memoryの正規Ownerと保存Portは本体構成に含む。DB障害は明示された保存方針に従い、記憶の永続化が成功したかを偽らない。復元・保存・再起動の試験は本体完成に必要。

Speechは意味計画・人物らしい言語化・検証・出力処理の責務を持つ。TTS/Presentationの外部提供先未構成を理由に意味経路を削除しない。Bodyは意思決定と独立した連続制御に従い、装置・アバターの接続有無と内部状態を区別する。

## 5. 受入基準

- 起動時に全必須Ownerが登録済みで、登録不足を成功として隠さない。
- 入力と内部契機の双方が意味解析・評価・自律判断へ到達する。
- 感情・欲求・目標・計画・活動・記憶が各Ownerの正しい状態遷移と出典を保持する。
- Speech / Body / Pluginの可用性、実行事実、失敗が創作されずに出力される。
- 並列処理・取消・現在性・縮退・資源解放が検証される。
- 実装コード・利用モジュール・採用する依存はPython 3.10.5を前提とし、Python 3.10.5でRuff、strict Mypy、全pytest、実PostgreSQL、起動停止の結合試験を通過する。他バージョンでの補助検証は、この必須検証の代替としない。
- 実LLM・実発話・自律活動・復元の動作と品質を確認し、模擬Portの成功だけで完成としない。

**段階別のテスト実行は許可するが、段階別の製品起動構成は認めない。** テストの期待値は確定済みの設計・公開契約から導き、現状のコードに合わせて設計上必要な検証を弱めない。重複した検査は統合できるが、必要な責務・失敗経路の検証は残す。進捗はこの唯一の本体の実装・受入れで判定する。

## 6. 廃止する契約

以下は本変更により製品構成の正本ではなくなる。

- `docs/architecture/v2/minimum_brain_production_configuration.md` の入力意味解析だけによる製品起動
- `docs/architecture/v2/system_production_cognition_configuration.md` のS2専用製品起動
- `--s2-production` と `build_s2_production_core`、`MinimumBrainProductionConfig` 等の旧API
- 「S1からS9を進めれば段階ごとの半製品が完成する」という扱い

歴史的な試験やIssueの番号は記録として保持しても、失効済みの起動方式を復活させてはならない。実装移行中に残る旧コードは移行未完了として管理し、完成と報告しない。

## 7. 本番設定の配置

本番設定と人物定義の唯一のルートは `config/` とする。`resources/` は不要であり使用も生成もしない。既存設定値の違いは `config/` 側の正本を保持する。`app/composition/` の責務は UseCase または Bootstrap へ移し、移設元は削除する。

コードとドキュメントに旧 S2 の型名・起動分岐・設定ファイル参照・自然言語の作業指示を残さない。テスト専用経路も `config/` の正本を扱う。

## 8. 起動構成のコード単位の責務分離

`app/bootstrap/system_cognition_configuration.py` を一枚の巨大な所有者にしない。対象を関数・クラス単位に分離する。

| 正規ファイル | 担当 | 禁止する責務 |
| --- | --- | --- |
| `app/bootstrap/composition_contracts.py` | 実行識別子、構成結果を記録する不変契約 | 外部I/O、起動停止、Provider生成 |
| `app/bootstrap/composition_snapshot.py` | 確定済みConfig/Ownerの来歴を型付きSnapshotへ射影 | Ownerの生成、状態遷移、リソースの取得 |
| `app/bootstrap/core_application.py` | 完成した本体を保持し、開始・停止を既存ライフサイクルへ委譲 | LLM設定の読み込み、個別認知の判断 |
| `app/config/core_resources.py` | 設定root配下の安全な参照読込と構成ID・revisionの一致検証 | Runtime Ownerの生成、認知の判断 |
| `app/bootstrap/system_cognition_configuration.py` | Configの読込関数を呼出し、検証済み値からOwnerを接続し構築失敗時に解放 | 設定ファイルI/Oの独自実装、構成DTO定義、認知結果の判定 |
| `app/bootstrap/cli_composition.py` | 標準CLIから同じ構成runへ明示Ownerを注入し、必須Ownerの未登録を失敗として返す | 必須Ownerの欠落を省略構成の成功として扱うこと |

製品の標準起動では、少なくともMemoryの未登録は構成失敗とし、Speech・Body等の未登録についても同じ完全構成の受入基準で扱う。**最初の欠落だけを拒否する修正は全Ownerが構成できた証明ではない。** 不足の状態と実装順は[受入対応表](unified_core_acceptance_matrix.md)で区別する。

異常は従来の `CoreConfigurationError` と失敗コードへ正規化し、構築失敗やキャンセル時の資源回収を省略しない。既存呼び出しが参照する公開名は移行期間だけ元の入口から明示的に再公開し、同じクラスの複製定義を作らない。改修後はクラス定義箇所の単一性、import恒等性、停止処理、Snapshotの値と全pytestを検証する。

設定の唯一の場所は `config/` とし、対象コード・テストに不適切な作業指示文を混入させず、旧構成の別経路を作らない。

## 9. ユースケースからInfrastructureへの逆依存排除

`app/usecases/` は外部の具象実装（`app.infrastructure`）をimportしない。取消と時計の契約は `app.runtime.kernel`、保存の失敗分類は `app.domain.contracts.persistence`、保存操作とメモリOwnerは `app.usecases` 内の既存単一定義を使う。

Speechの具体的な子process Supervisorの有無と接続の安全性は `app/bootstrap/speech_production_configuration.py` が組立て時に検査する。`CoreSpeechPipeline` は `SpeechPresentationExecutionBoundary` 抽象Portを受け、実装がprocess Supervisorかどうかを調べない。これにより具象の差替え時も認知・Speechの意味規則を変えない。

検証条件は、ユースケースからInfrastructureへの直接importがないこと、既存型と公開結果の恒等性を保つこと、正式組立て時のSupervisor検証を維持すること、取消・失敗・提示の全経路の回帰試験とする。

## 10. アーキテクチャ試験の正本参照

構造検査は移設後の実定義を対象とする。`CoreApplication` の開始・終了メソッドは `app/bootstrap/core_application.py`、入力意味と評価の配送Portは `app/usecases/cognition_delivery.py` をAST検査する。`app/bootstrap/system_cognition_configuration.py` は構成・接続に限定し、`CoreApplication` を再定義しない。

移設前の `app/composition/` を参照する試験を復活させず、現在のクラスと関数の責務（認知Portの型付き引数、起動ライフサイクルの委譲、Domainへの依存方向）を検証する。テストが通っても、実DB・実起動を含む本体の完了判定は別に実施する。

## 11. 並行認知の結果観測

起動時の主観評価と利用者入力の認知処理は別traceとして並行する。統合検証では最初に到着した結果を投入入力の結果と決めつけず、work_idまたはtrace_idとmoduleの一致を確認する。自律評価を停止して試験を成立させることは認めない。実DB障害時には保存の型付き障害と認知結果を独立に検証する。

## 12. Brain結果の検証と単一の受信責務

起動時の自律的な主観評価や並行作業による公開結果は、利用者が投入したworkの結果より先に届いてよい。検証用consumerは対象work ID集合を明示し、共有する一つの期限内で対象結果を照合する。対象外の結果で正常な入力結果を代用しない。複数workの場合も各work IDを一度だけ確認し、無限待機をしない。

テスト専用の共通観測処理を`tests/helpers/brain_outcomes.py`へ配置する。本体のBrain Kernel・自律評価の処理・結果publishの順序には手を加えず、公開結果の型とfailureを従来どおり検査する。完了時には既存の外部利用者併用試験と入力参照の採用試験を実行し、結果の正しい帰属を確認する。

## 13. 並行結果照合ヘルパーの単一契約

検証用の `next_outcome_matching` は `work_id`、`trace_id`、module、statusの指定条件で公開Brain結果を選び、条件に一致しない結果をBrainごとの一時保管領域に保持する。次の照合呼出しは保管済み結果を先に確認し、先着順に依存せず、対象外の自律評価を失わない。照合には少なくとも一つの条件と有限期限が必要であり、取消時も既に取り出した他traceの結果を捨てない。

`collect_work_outcomes` と単一work待受はこの照合関数を共用し、期限は呼出し全体で一回だけ定義する。保管領域の所有は検証専用とし、実行中のBrain Kernelや正規Ownerへ製品側の隠れた状態を追加しない。弱参照により検証Brainが破棄されれば保管領域も破棄可能とする。

## 14. 検証基盤自身の失敗診断

検証処理が `HARNESS_FAILED` に分類された場合、公開結果には検証用の失敗区間名と例外の**型名だけ**を付記し、例外の本文、接続先、SDK応答、パスワード、鍵、URL、Provider生データを掲載しない。これにより製品動作の例外（`PRODUCT_FAILED`）と検証処理の障害を混同せず、根本原因を追跡できる。検証が所有する資源の回収と、既存の状態分類・遮断判断は保持する。

失敗段階は完了済みの計測区間から、`HARNESS_FAILED` に分類された最初の区間の `stage` を使う。正常終了区間を誤って原因扱いせず、計測記録が存在しない例外のみ `runner` を報告する。

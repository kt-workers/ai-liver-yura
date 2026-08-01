# Game Subsystem

このディレクトリは、将来Coreとは別プロセスで実装するGame Subsystemの境界を示す。

現時点ではゲーム実装、API server、DB、transport adapterを含まない。Python側の正本は`app/integrations/games/`にある中立DTO、Gateway Protocol、Null Gatewayである。

将来のSubsystemはゲームルール、セッション、入力検証、勝敗、NPC、永続化を所有する。Coreへゲーム固有型を公開せず、旧Games Pluginやしりとり実装も再利用しない。

未接続は異常終了ではなく`DISCONNECTED`として扱う。接続利用者が追加されるまではRuntimeへGatewayを注入しない。

外部通信契約を追加する場合は、[contracts/README.md](contracts/README.md)の方針に従う。

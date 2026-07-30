# Game Subsystem外部契約

将来、HTTP、WebSocket、message broker等のプロセス間通信を導入する際のschema配置先である。現時点ではschemaを確定せず、Python側の`app/integrations/games/`を意味上の正本とする。

外部schemaは次の条件を満たすこと。

- status、Command、Command結果、Event、Snapshotの意味を維持する
- enum値と`game_subsystem_not_connected`を安定識別子として扱う
- payloadを言語中立なobjectとして表現する
- Core内部型、Python固有型、個別ゲーム型を含めない
- versioning、互換性、idempotency、Event cursorを明記する

transport adapterとschemaが必要になった時点で、OpenAPI、AsyncAPI、JSON Schema等の形式をユースケースに合わせて選択する。

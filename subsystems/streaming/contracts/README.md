# Streaming Subsystem公開契約

このディレクトリは、将来Core、Streaming Subsystem、Streaming Adminがプロセス境界で共有するschemaの配置先である。

現時点ではtransportとserialization形式を確定せず、`app/integrations/streaming/`のPython DTOを意味上の参照実装とする。公開契約versionは`1.0`である。

外部schemaを追加する場合は次を守る。

- Command、Query、Eventを分離する
- Event EnvelopeにAPI version、sequence、不透明cursorを含める
- Operation requestに任意の不透明idempotency keyを含める
- timestampはRFC 3339 UTC、IDは不透明文字列として表現する
- 同一majorのoptional field追加を許容し、未知fieldを無視する
- 未知enumとerror codeを公開契約文書の安全なfallbackで扱う
- YouTube、OBS、Google API、Core Runtime、Admin API、transport固有型を含めない

HTTP、WebSocket、IPC等の方式とOpenAPI、AsyncAPI、JSON Schema等の形式は、Subsystem外枠と利用者が実装される段階で選択する。

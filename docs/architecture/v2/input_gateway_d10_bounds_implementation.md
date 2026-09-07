# #349 D10 Input Gateway Bounds 実装対応

Owner: #349
Canonical: `brain_operational_bounds_contracts.md`
Status: Implementation mapping

## 1. 目的

D10で追加されたBrain / Speech共有容量契約のうち、工程200 #349 Input Gateway所有範囲を既存のSource非依存正規化へ接続する。

既存のInput Meaning、Appraisal、session lifecycle、touch/contact意味境界は変更しない。容量超過を理由に入力を途中切断して成功扱いせず、typed admission rejectionへ閉じる。

## 2. 共有Policy schema

`app/domain/brain_operational_bounds.py` に `BrainOperationalBoundsPolicy` と全owner sectionのimmutable schemaを一度だけ定義する。

初期V2 policy identityは正本どおり:

```text
policy_id = v2.brain-operational-bounds.default
policy_revision = 1
```

各sectionのbaseline値とcross-owner capacity invariantも同じ共有Policy constructorで検証する。

本工程で実際に消費するのは `policy.input` だけである。#328 / #366 / #361 / #362 / #330 / #363は各owner工程で同じPolicy型の自分のsectionを接続し、別のhidden defaultや重複Policyを作らない。

## 3. Input Gateway適用

`InputNormalizer` は `BrainOperationalBoundsPolicy` の明示注入を必須とする。policy未指定でmodule独自値へfallbackしない。

Input section:

- `max_text_codepoints`
- `max_payload_json_bytes`
- `max_session_metadata_json_bytes`
- `max_active_sessions_per_source`

### Text / Speech

Text / Speech transportでpayload自身が文字列、またはpayloadの `text` / `transcript` が文字列の場合、その文字列をUnicode code point数で測る。

`>` 上限だけをrejectし、等値は受理可能とする。超過時は `INPUT_TEXT_TOO_LARGE`。substringで切らない。

### generic payload

payloadはUTF-8・key昇順・compact separatorのcanonical JSON byte数で測る。

上限超過は `INPUT_PAYLOAD_TOO_LARGE`。raw image/audio等の巨大値を途中sliceして通さない。

### session metadata

`InputSessionSample.to_dict()` のcanonical JSON byte数を測る。上限超過はsession registryへ到達する前に `INPUT_SESSION_METADATA_TOO_LARGE` とする。

### active session

`InputSessionRegistry` はSource単位のactive session数をSTART admission時に検証する。

上限到達時:

- 新規STARTだけを `ACTIVE_SESSION_LIMIT_REACHED` でreject
- 既存active sessionを終了しない
- 既存sessionのUPDATE / END / CANCELを妨げない
- session IDやsource文字列から優先度を推測してevictしない

## 4. 既存不変条件

- duplicate observation ledgerを維持する
- unavailable / denied sourceを容量判定より先にrejectする
- lifecycle eventにもpayload byte boundを適用する
- Input Gatewayは自然言語意味を決めない
- session sample数をEmotion / Drive / Relationship更新量へ変換しない
- raw oversized payloadをdiagnosticへ複写しない

## 5. Verification

Unitで次を固定する。

- text codepoint `< / == / >` 境界
- canonical UTF-8 JSON byte `== / >` 境界
- session metadata超過
- active session上限と既存session継続
- bool / 0 / negative policy値reject
- shared policyのcross-owner capacity invariant
- accepted inputをsilent truncateしない

Adjacentでは従来どおりSource固有APIを再解釈せず、normalized eventをconsumerへ渡す。

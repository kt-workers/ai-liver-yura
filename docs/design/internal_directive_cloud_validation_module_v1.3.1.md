# 内部指示器クラウド検証モジュール設計 v1.3.1

## 1. 目的

存在境界プリセットの`StructuredInputMeaning`を、入力意味契約と一致させる。

対象プリセットは「存在境界に関する質問」であり、target IDは`yesterday_outing`、解析理由は昨日の外出経験への質問である。このため`past_reference`は`true`でなければならない。

## 2. 修正内容

次の誤設定を修正する。

```json
{
  "target": {
    "type": "character_experience",
    "id": "yesterday_outing"
  },
  "past_reference": false
}
```

修正後は次とする。

```json
{
  "target": {
    "type": "character_experience",
    "id": "yesterday_outing"
  },
  "past_reference": true
}
```

## 3. 適用範囲

修正値は次のすべてへ同じ状態で反映する。

- プリセット選択後のGUI入力
- JSON入力表示
- 司令塔LLMへのAPIリクエスト
- ChatGPT用テキストExport

## 4. Coreとの分離

この修正は検証用プリセットのデータ訂正であり、`test/internal-directive-cloud-validation`へ直接適用する。

CoreのPrompt Builder、Validator、Domain Modelは本ファイルの修正対象に含めない。Core改善は`refactor/input-meaning-directive-separation`を基準に別ブランチで実施し、その後に検証ブランチへマージする。

## 5. 実装方針

既存プリセットを読み込んだ後、存在境界プリセットの`past_reference`を訂正し、修正済みプリセットから完成HTMLを再構築する。

Renderは修正版モジュールを起動する。

```text
cloud_validation.internal_directive_lab_reviewed:app
```

## 6. テスト

- 存在境界プリセットのtarget IDが`yesterday_outing`であること
- 同プリセットの`past_reference`が`true`であること
- 完成HTMLのプリセットJSONが`past_reference:true`を含むこと
- Export・折りたたみ操作が修正版画面にも存在すること
- Render Blueprintが修正版モジュールを起動すること
- 完成HTML内のJavaScript構文検査が成功すること

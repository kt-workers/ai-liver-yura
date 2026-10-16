# V2 Character Definition Resource Location Amendment

Owner Issue: #355
Parent: #324
Related content owner: #354 / #442
Supersedes: `character_projection_contracts.md` §2.2 の production data location
Status: Canonical Amendment

## 1. 目的

Character Definition のmachine-readable mirrorをrepository root直下の専用bucketへ置かず、Runtimeが読み取るversioned static resourceとして明示する。

人物設定の意味、schema、certainty、projection、loaderの責務は変更しない。本補足はstorage locatorだけを置き換える。

## 2. 正本とresourceの分離

```text
docs/character/v2/*
  Human-readable Character Bible
  semantic authority
          ↓ explicit authoring sync
resources/character_definitions/v2/<character_id>.yaml
  machine-readable read-only Runtime resource
          ↓ YAML loader / deterministic projector
Typed Runtime Profiles
```

- `docs/character/v2` は人物設定の意味上のAuthorityを維持する。
- `resources/character_definitions/v2` はRuntime convenience用mirror / compile inputであり、人物設定を独自に発明しない。
- `app/config` はruntime operation / service configurationの領域であり、Character contentを配置しない。
- repository root直下の `character_definitions/` は旧locatorとし、新規・復活を禁止する。

## 3. Production locator

D10後のproduction locatorを次で固定する。

```text
resources/character_definitions/v2/<character_id>.yaml
```

現行ゆらdefinition:

```text
resources/character_definitions/v2/yura.yaml
```

storage path自体はDomain Authorityではない。将来package resource / DB等へ置換しても `CharacterDefinitionDocument`、loader schema、projector contractは変更しない。

YAML Adapterは引き続きYAML bytes/textを受け取り、repository pathを内部へhard-codeしない。locatorの解決はAdapter外側のcomposition/resource loading責務とする。

## 4. Migration invariant

旧:

```text
character_definitions/v2/yura.yaml
```

新:

```text
resources/character_definitions/v2/yura.yaml
```

移設時はYAML blobをbyte-identicalに維持する。`schema_version`、`definition_revision`、facet値、certainty、Bible provenanceを変更しない。

したがって本移設はCharacter content revisionではなくstorage organization revisionである。

## 5. Verification

- 新production locatorからstrict YAML loadできる。
- projectorのLanguage / Voice / Body / Psychological Profileが従来どおり生成される。
-旧 `character_definitions/v2/yura.yaml` が存在しない。
- YAML content blobが移設前後で同一である。
- full deterministic CIでpath依存の未移行consumerがないことを確認する。

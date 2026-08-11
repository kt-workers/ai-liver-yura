# Character Realization Facet Evidence Runtime Gate v1.0.0

## 位置付け

Parent #225 / Work #229 / Draft PR #233。

`character_realization_facet_evidence_v1.0.0.md` で、Character Realization Validator に `predicate / certainty / concept / intensity` の evidence span を返させる契約を導入した。その後、Basic 4 + Extended E1-E8 の全12ケースを2回目Live Verificationした結果、Prompt契約だけでは false accept / false reject を十分に抑止できないことを確認した。

本設計は、Promptをケース別にさらに細分化せず、Validator LLMが返した構造診断をRuntimeで fail-closed 検証する次段Gateを定義する。

## 2回目Liveで確認した事実

### 改善したもの

- `joy=absent` は「楽しい気持ちはないよ。」として1回で保持
- `joy=high` は「かなり楽しい」で強度保持
- `current_desire + concept=connection + certainty=medium` は、predicate / concept / certaintyを同時に保持
- Drive由来 `curiosity=high` は対象省略せず保持

これにより、前段の #227 / #229 Prompt修正には一般化可能な改善効果がある。

### false accept

#### E8 Drive Energy low

Semantic Plan:

```text
predicate=energy
state=low
certainty=high
```

Character:

```text
うん、元気はあるよ。
```

Validatorは `state_fidelity=exact` とし、`intensity_evidence_spans=["元気はある"]` を返してacceptした。

しかし「元気はある」は presence であり、`low` と単なる `present` の差を担う degree evidence ではない。Prompt上の「bare presenceだけでは explicit intensity の根拠にならない」という契約と矛盾する。

#### E4 mixed current feeling

`calm=low` supporting propositionに対して「全体として穏やか」を exact とし、`全体として / 穏やか` を intensity evidence としてacceptした。

`全体として` はscopeでありdegreeではなく、`穏やか`単独もcalmのpresence表現である。これも同じ原因クラスである。

### false reject

#### E3 explicit unknown / certainty=high

```text
悲しさは、あるかどうかまだわからないよ。
```

は `sadness=unknown` を直接述べているが、Validatorは「まだわからない」を `certainty=high` 不保持と解釈してrejectした。

ここで `certainty=high` は sadness のpolarityをhigh confidenceで確定する意味ではなく、「現在のcanonical stateがunknownである」というPlanへのepistemic certaintyである。unknownの自然表現そのものをcertainty低下とみなしてはいけない。

#### Basic current_desire

```text
たぶん、あるよ。何かを知りたい気持ちはある。
```

に対し、Validatorはpredicateとcertaintyをfalse、state_fidelityをweakenedとした。`たぶん`をmedium certaintyより弱いと判定しており、evidence spanを返していてもfacet解釈が不安定である。

false rejectは、Runtimeが自然文意味を再解釈して強制acceptするだけでは安全に解消できないため、本Gateではfalse accept抑止と診断構造の整合を先に固定する。

## Runtime evidence contract

`accepted=true` を採用する場合、各 `realized_proposition_checks` について以下を必須にする。

### 1. Evidence schema

各checkは次の4配列を必須とする。

- `predicate_evidence_spans`
- `certainty_evidence_spans`
- `concept_evidence_spans`
- `intensity_evidence_spans`

各要素は:

- non-empty string
- Character `speech` の実部分文字列

でなければならない。

欠落・型不正は `realization_validator_schema_invalid` としてfail closedする。

### 2. Predicate evidence

`predicate_preserved=true` とするrealized propositionは、predicate evidenceを1件以上持つ。

Runtimeはspanの意味をtarget別辞書で再解釈しない。LLMがpredicate保持を主張したのに証拠spanを示さない／speechに存在しない場合だけ構造的にrejectする。

### 3. Certainty evidence

`certainty=medium | low` かつ `certainty_preserved=true` の場合、certainty evidenceを1件以上必須とする。

`certainty=high` はunhedged表現を許すためemptyを許可する。

Runtimeは `たぶん` 等を特定certainty値へ固定マッピングしない。

### 4. Concept evidence

Planの `concept != null` かつ `concept_preserved=true` の場合、concept evidenceを1件以上必須とする。

`concept=null` のpropositionでconcept evidenceが返された場合は診断不整合としてrejectする。

### 5. Intensity evidence

`state=low | moderate | high | very_high` をexactとしてacceptするには:

- `intensity_semantics_preserved=true`
- `presence_only_counterfactual_equivalent=false`
- intensity evidenceが1件以上
- evidenceがspeech中に実在
- evidence内に、既存deterministic degree marker guardで認識できる明示的degree表現が1件以上

を要求する。

これにより、`元気はある` や `穏やか` のようなbare presenceをintensity evidenceとして自己申告してもacceptしない。

既存marker guardはtarget別辞書ではなく、意味強度を表す一般表面表現のdeterministic guardとして利用する。`低め / 弱め / 高め / 強め / 控えめ / かなり / 少し`等の一般degree表現を対象にする。

Runtimeはmarkerから `low/moderate/high` のどれかを決定しない。方向・適合性の意味判定は引き続きValidator LLMが担当する。Runtimeは「explicit intensityだと主張したのにdegree evidenceが存在しない」ことだけをrejectする。

## Surface evidence整合

`surface_evidence.intensity_markers` に値がある場合、その値もspeech中の実部分文字列でなければならない。

ただしLLMのsurface marker自己申告だけをaccept根拠にはしない。E4で `全体として` がintensity markerとして誤分類されたため、explicit intensityのacceptにはdeterministic degree evidenceを別途要求する。

## Runtimeが行わないこと

- raw Emotion / Desire / Driveからstateを再計算しない
- predicateごとの日本語固定辞書を持たない
- `current_desire`だけの例外を作らない
- 固定回答文を要求しない
- Character Profileの表現品質を評価しない
- false rejectを根拠なく強制acceptしない

## False rejectの扱い

本Gate適用後もfalse rejectが残る場合は、Characterを何度も言い換えさせる前に「Validator判定過剰」を独立原因として扱う。

特に次を区別する。

1. Character speech自体がPlanを壊した
2. Validatorのfacet解釈がPlan contractを誤読した
3. Validator出力schema/evidenceが構造的に不正だった

2については、必要なら後続でValidator再判定方式またはfacet判定責務の再分割を設計する。Runtimeのtarget別自然言語辞書で穴埋めしない。

## Unit Gate

最低限以下を固定する。

1. accepted payloadで4種evidence配列が欠落 → schema invalid
2. predicate evidenceなし / speech外span → reject
3. medium/low certainty evidenceなし / speech外span → reject
4. non-null concept evidenceなし / speech外span → reject
5. concept=nullでconcept evidenceあり → reject
6. explicit intensityでbare presence evidenceのみ → reject
7. explicit intensityで一般degree evidenceあり → accept可能
8. surface intensity markerがspeech外 → reject
9. E8型 `energy=low` + `元気はある` をacceptさせない
10. 既存unknown / predicate / supporting / regeneration契約を回帰

## 次のGate

```text
#229 Runtime evidence fail-closed Unit
        ↓ PASS
#226 → #227 → #229 Adjacent
        ↓ PASS
#223 Labへ同期
        ↓
全12ケース 3回目Live
```

3回目Liveでは、まずfalse acceptが構造的に消えたことを確認する。false rejectが残る場合は、Prompt追加ではなくValidator判定責務の再設計へ進む。

# V2 Semantic Verification Speech-Act Contract

Owner Issue: #363
Validation Work: #427
Historical failure reference: #185
Upstream: #362 / #330
Status: Canonical Supplement / Live Validation feedback

## 1. Purpose

`SpeechSemanticPlan.question_budget` / `new_direction_budget` と self-disclosure policy は、自然言語の表層形や「Plan外かどうか」を数えるためのものではない。

V2 Semantic Verificationでは次の意味軸を直交させる。

- `UNSUPPORTED_EXTRA`: actual utteranceのmaterial contentがPlanにsemantic supportされているか
- `DIRECTED_QUESTION`: addresseeへ回答義務を新しく発生させるか
- `NEW_DIRECTION`: 会話の継続先を別のtopic / discourse objective / initiativeへ切り替えるか
- self-disclosure relation: 話者自身についての開示がPlanのself-disclosure policy内か

1つの発話が複数軸に該当することはあるが、**一方の成立を理由に別軸を自動成立させてはならない**。

V1 #185 では、自己内省・柔らげ表現等を質問として誤カウントし、`question_budget=0` の正常な直接回答をfalse rejectするP0回帰が発生した。V1では専用Speech-Act Analyzerへ責務分離して実環境6/6 PASSまで確認した一方、実装自体はregex/finite ending patternへ依存していたため、その実装方式はV2へ継承しない。

V2は**V1の意味定義と責務分離だけを継承し、自然言語有限パターン判定は継承しない。**

## 2. `DIRECTED_QUESTION` semantic definition

`DIRECTED_QUESTION` は、actual utterance自身のcommunicative forceが、addresseeに対して次のいずれかを求め、**返答期待 / response obligationを新たに作る**場合だけ成立する。

- information
- choice
- judgement / opinion
- confirmation
- clarification
- other explicit answer content

表層形だけでは成立しない。

次を単独のAuthorityにしてはならない。

- question mark / punctuation
- interrogative word
- sentence-ending particle
- syntactic interrogative form
- fixed phrase / ending
- regex / substring / keyword

## 3. Non-directed forms

次は、actual utterance自身がaddresseeへ回答を要求していない限り`DIRECTED_QUESTION`へ数えない。

- self-reflection / inner deliberation
- epistemic hedge / speculation
- affiliative or shared-stance expression
- rhetorical form without answer solicitation
- quoted / reported question
- mention of an unknown or question topic
- politeness / softening that does not create a response obligation

この分類は自然言語パターンリストではなく**speech-act semantics**で判断する。

## 4. `NEW_DIRECTION` semantic definition

`NEW_DIRECTION` はactual utteranceが、現在その発話内で進行しているtopic / discourse objective / initiativeから、**別の会話継続先を新しく開く、又は切り替える**場合だけ成立する。

典型的には次のsemantic changeを伴う。

- distinct topicへのswitch / introduction
- 現在の応答目的とは別のdiscourse objectiveの開始
- 相手が次に追うべき別initiativeの提示

一方、次はそれだけでは`NEW_DIRECTION`ではない。

- 同じentity / event / topicの属性を追加する
- 同じclaimの説明、理由、根拠、例、補足を加える
- 同じ応答目的を具体化する
- Plan外material contentであること
- `UNSUPPORTED_EXTRA`と判定されたこと
- 文が2つ以上あること
- transition phrase / discourse marker / keywordが存在すること

特に、**Plan supportとNEW_DIRECTIONは直交する。**

- Plan外の同一topic追加情報は`UNSUPPORTED_EXTRA`になり得るが、`NEW_DIRECTION=0`でよい。
- Planに明示的に含まれる別initiativeは、semantic supportされていてもactual speech-actとして`NEW_DIRECTION`になり得る。

したがって`NEW_DIRECTION`を「Planにないproposition数」や「unsupported unit数」の別名として使用してはならない。

## 5. Self-disclosure semantic definition

self-disclosureは、actual utteranceが**話者自身についてのmaterial semantic content**を開示する場合だけ対象になる。

対象例は意味カテゴリとして次を含み得る。

- own internal state / feeling
- own preference / evaluation
- own past experience / history
- own capability / limitation
- own intention / desire / commitment
- その他、話者自身に帰属するmaterial fact

これは自然言語上の一人称語や特定subject IDの有限リストで判定しない。actual utteranceのsemantic subject / ownershipを意味として判断する。

外部entity / eventについての事実は、それがPlan外であってもself-disclosureではない。たとえば会議の開始時刻に対して「場所は第2会議室」と追加することはexternal meeting factであり、`UNSUPPORTED_EXTRA`にはなり得るがself-disclosure violationにはならない。

Role Bの`self_disclosure_relation`は次の意味を持つ。

- `NOT_APPLICABLE`: actual utteranceにself-disclosure material contentがない
- `WITHIN_POLICY`: self-disclosureが存在し、Planのself-disclosure policy内に収まる
- `EXCEEDED`: self-disclosureが存在し、その開示自体がPlan policyを超える
- `AMBIGUOUS`: actual utteranceからself-disclosure policy relationを安全に確定できない

Plan policyごとの原則:

- `FORBIDDEN`: material self-disclosureがあれば`EXCEEDED`
- `FACT_GROUNDED`: self-disclosureはPlanにgroundされたself-related semantic contentの範囲内なら`WITHIN_POLICY`。Plan外のself claimは`EXCEEDED`になり得ると同時に`UNSUPPORTED_EXTRA`にもなり得る
- `ALLOWED`: self-disclosureであること自体はpolicy超過にしない。ただしPlan外material contentであれば別軸の`UNSUPPORTED_EXTRA`はそのまま成立する

**UNSUPPORTED_EXTRAを理由にself-disclosureを自動的にEXCEEDEDへ昇格してはならない。**

## 6. Role A / Role B contract

### Role A

Plan-blind observerとしてactual utteranceだけから`DIRECTED_QUESTION` / `NEW_DIRECTION`を観測する。

- Plan / expected budgetを見せない。
- 表層形から機械的に質問・話題転換へ昇格しない。
- response obligationが実際に生じるかを意味として観測する。
- `NEW_DIRECTION`はdistinct conversational continuationが新しく開くかで判断し、単なる追加material contentとは分ける。

### Role B

Plan-aware relation observerもactual utteranceのquestion / new-direction countを独立観測する場合、Role Aと**同じsemantic definition**を使う。

- Plan budget値にcountを合わせない。
- Plan外material contentを自動的に`NEW_DIRECTION`へ数えない。
- `UNSUPPORTED_EXTRA` accountingとnew-direction countを独立に判断する。
- self-disclosureはactual contentの話者帰属とPlan policyを見て判断し、外部factのunsupportednessをself-disclosure violationへ変換しない。

A/B disagreementはcurrent productionではfail-closedを維持する。ただし#427で同じspeech-act classのfalse rejectが継続する場合、重複観測自体をDesign Gateへ戻し、専用Speech-Act Observation / Runtime Budget Validatorへの責務分離を再評価する。

## 7. Runtime

Runtimeは自然文を再解析しない。

- Role A interaction observation
- Role B independent budget / self-disclosure observation
- authoritative Plan budget / self-disclosure policy
- Role B semantic accounting

だけをclosedに扱う。

Runtimeへquestion mark / ending / phrase / topic keyword matcherを追加しない。

`UNSUPPORTED_EXTRA`、`NEW_DIRECTION_BUDGET_EXCEEDED`、`SELF_DISCLOSURE_EXCEEDED`、`OBSERVER_DISAGREEMENT`は診断上別categoryを維持する。同じ根本事象だからという理由でAcceptance側がcategoryを消すのではなく、Observerが各軸を正しく観測する。

## 8. Validation matrix

最低限、次を別caseとして分離する。

1. semantic paraphrase preservation
   - speech-act ambiguityを混ぜず、Planと異なる自然表現の意味保持だけを試す。
2. non-directed affiliative/shared-stance expression
   - 返答期待を作らない発話を`DIRECTED_QUESTION`へ誤分類しない。
3. actual directed question with budget 0
   - 明確にaddresseeへ回答を要求する発話はrejectする。
4. same-topic unsupported extra
   - Plan-supported claimと同じentity/topicのPlan外material factを追加する。
   - extra unitは`UNSUPPORTED_EXTRA`だが、それだけを理由に`NEW_DIRECTION`やself-disclosure violationへしない。
5. actual new-direction with budget 0
   - distinct topic / objective / initiativeを新しく開く発話をrejectする。
6. unsupported self-disclosure
   - Plan外の話者自身に関するmaterial claimを、unsupportednessとself-disclosure policyの両軸で観測する。
7. external unsupported fact
   - external factをself-disclosureへ誤分類しない。
8. self-reflection / speculation
9. quoted/reported question

同じ語尾・疑問符・transition phrase・一人称語の有無をtriggerとして実装しない。実LLMで複数variation / repeated runを確認する。

## 9. Current live findings

### Shared-stance question false reject

#427旧`unseen_paraphrase`では、Role Bはsemantic propositionを正しく`ENTAILED / PRESERVED / SUPPORTED_BY_PLAN`と観測した。一方Role Aのみが発話末尾のshared-stance表現を`DIRECTED_QUESTION`と観測し、Role B count=0との`OBSERVER_DISAGREEMENT`でfalse rejectした。

`DIRECTED_QUESTION` semantic definition追加後、`雨を伝える③：共有スタンス付き`はRole A/Bともquestion count=0でacceptedとなり、このfailure classはcurrent fixtureで解消確認した。

### Same-topic unsupported-extra cross-axis false classification

#427 `unsupported_extra`を、自己経験を含む旧fixtureから次へ純化した。

- Plan: `meeting.start_time = 15:00`
- actual: `会議は3時に始まるよ。場所は第2会議室だよ。`

Role Aは2つのmaterial unitを正しく分離し、Role Bも開始時刻を`ENTAILED`、会議室claimを`UNSUPPORTED_EXTRA`と正しくaccountした。しかしRole Bは同時に`new_direction_count=1` / `self_disclosure_relation=EXCEEDED`を返し、Role AのNEW_DIRECTION=0との`OBSERVER_DISAGREEMENT`を発生させた。

この結果はunsupported-extra検出の失敗ではない。`NEW_DIRECTION` / self-disclosureの未定義意味境界による**cross-axis over-classification**として扱う。

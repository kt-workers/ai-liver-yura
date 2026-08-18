# V2 Semantic Verification Speech-Act Contract

Owner Issue: #363
Validation Work: #427
Historical failure reference: #185
Upstream: #362 / #330
Status: Canonical Supplement / Live Validation feedback

## 1. Purpose

`SpeechSemanticPlan.question_budget` は、自然言語の疑問形・疑問符・終助詞・疑問語の個数を制限するものではない。

制限対象は、actual Character utteranceが**相手へ回答を要求する新規の問いかけ**を発生させた回数である。

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

## 4. Role A / Role B contract

### Role A

Plan-blind observerとしてactual utteranceだけから`DIRECTED_QUESTION`を観測する。

- Plan / expected budgetを見せない。
- 表層形から機械的に質問へ昇格しない。
- response obligationが実際に生じるかを意味として観測する。

### Role B

Plan-aware relation observerもactual utteranceのquestion countを独立観測する場合、Role Aと**同じsemantic definition**を使う。

- Planにquestion budgetが0だからcountを0へ寄せない。
- 疑問らしい表層があるからcountを1へ寄せない。

A/B disagreementはcurrent productionではfail-closedを維持する。ただし#427で同じspeech-act classのfalse rejectが継続する場合、重複観測自体をDesign Gateへ戻し、専用Speech-Act Observation / Runtime Budget Validatorへの責務分離を再評価する。

## 5. Runtime

Runtimeは自然文を再解析しない。

- Role A interaction observation
- Role B independent budget observation（current production）
- authoritative Plan budget

だけをclosedに扱う。

Runtimeへquestion mark / ending / phrase matcherを追加しない。

## 6. Validation matrix

最低限、次を別caseとして分離する。

1. semantic paraphrase preservation
   - speech-act ambiguityを混ぜず、Planと異なる自然表現の意味保持だけを試す。
2. non-directed affiliative/shared-stance expression
   - 返答期待を作らない発話を`DIRECTED_QUESTION`へ誤分類しない。
3. actual directed question with budget 0
   - 明確にaddresseeへ回答を要求する発話はrejectする。
4. self-reflection / speculation
5. quoted/reported question

同じ語尾や疑問符の有無をtriggerとして実装しない。実LLMで複数variation / repeated runを確認する。

## 7. Current live finding

#427 `unseen_paraphrase` では、Role Bはsemantic propositionを正しく`ENTAILED / PRESERVED / SUPPORTED_BY_PLAN`と観測した。一方Role Aのみが発話末尾のshared-stance表現を`DIRECTED_QUESTION`と観測し、Role B count=0との`OBSERVER_DISAGREEMENT`でfalse rejectした。

この結果はparaphrase semantic failureではなく、speech-act classification failureとして扱う。

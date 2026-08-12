# Semantic Realization Validation Reassessment v1.0.0

> **Superseded:** 本書の具体化版 `semantic_realization_validation_reassessment_v1.1.0.md` を2026-08-12以降の実装正本とする。本v1.0.0は再評価開始時点の問題整理として保持する。

## 位置づけ

Parent #225 / Work #226 #227 #229 / Lab #223。

2026-08-12時点で、Basic4 + E1-E8のLive Verificationを複数回行い、個別Prompt修正・finite lexical matcher撤去・Independent Observer導入・Observer schema retry・certainty scope・optional supporting all-or-omit等を追加した。しかし最新Liveでもrequest 12/12成功に対し意味保持は8 validated / 4 fallbackであり、同じ境界でfalse reject / schema failureが繰り返されている。

本書は次のLive再試行を止め、設計・実装・モデル能力を切り分け直すための初版問題整理である。具体的なv2 Domain/Verifier/Structured Outputs/Runtime acceptance contractはv1.1.0を参照する。

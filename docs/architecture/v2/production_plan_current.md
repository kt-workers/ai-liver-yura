# V2 現行製造計画

状態: #550 再計画中

製造起点: `rebuild/v2-foundation@e054f21595c78052c6a791e6af7758ad51e1fd7c`

## 正本と除外

この計画は、V2アーキテクチャ正本索引、D10設計監査、各Issueの現在の`Depends on`、およびGitHub上のPR・merge状態から導出する。`production_sequence_authority.md`と`project_sync_manifest.md`の工程・日付は履歴資料であり、現行の製造順を決めない。Project #6は変更しない。

## 監査済み成果

Foundation、Brain、Speech、Memory、Body基盤、Infrastructureの各Unitはtrunkへ統合済みである。#341、#346、#546はそれぞれPR #541、#542、#548で統合済みだが、Issue状態の再照合は管理上の後続作業とする。#544はclosed/unmergedの検証専用系列であり、製造開始点にも依存関係にも含めない。#545で発見した#546の制動不具合は、#546のproduction修正知見としてのみ保持する。

## 依存グラフからの次順

1. #344 Plugin Integration: #334 と #343 が完了しており、最初の未完了かつ依存可能なproduction Integration。
2. #434 Speech Character Quality: 必須のSpeech依存が完了後、現行の実提示経路でのみHuman Verificationを行う。
3. #351 GUI/Admin: #344と#341の完了後に着手する。
4. #365 Game Skill、#352 Validation Labs、#353 Development Tooling: 各Issueの現行実装・canonical適合を再照合し、未完了分だけを実施する。
5. #360 System Integration: #344/#351/#352/#365を含む直接依存の完了後に実施する。

Parent Issueは子Workの状態監査後にのみ完了扱いにする。Human Verificationは各canonicalの完了条件が要求する場合だけ実施し、専用画面やLabを先行して作らない。

## 変更規則

新しいWorkは現行canonicalの独立責務または明示的な不具合に限る。各Work開始前にGitHub liveで対象Issue、canonical、既存PR/branch、base/head、CI、reviewを再確認し、Resume Certificateを記録する。

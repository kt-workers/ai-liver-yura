# V2 Deterministic CI — Issue #406

## 1. 目的

V2開発の機械検証をCodex / Gemini等の外部AIから分離し、GitHub Actionsだけで再現可能なPASS / FAILを、**PRのexact headと検証時点のlive target generationの組**へ紐付ける。

CIは設計妥当性やキャラクター性を判断しない。次の機械検証だけを所有する。

- full pytest
- Ruff
- Mypy strict
- Python compileall
- live base...head `git diff --check`
- merge freshness / regression guard
- repository dependency source invariant

## 2. Trigger

対象は`rebuild/v2-foundation`をbaseとする`pull_request`と、merge直前の明示`workflow_dispatch`。

PR作成・再open・head更新・Ready化時に実行し、Draft PRも検証対象とする。

workflowは`pull_request_target`を使わない。secretを渡さず、`GITHUB_TOKEN`権限は`contents: read` / `pull-requests: read`だけとする。

## 3. Exact identity contract

CIはevent payloadだけをAuthorityにしない。最初にGitHub live PRを取得し、次を解決する。

- live PR head SHA
- base ref
- base refのlive branch SHA

`workflow_dispatch`ではcallerが`expected_head_sha`を指定し、live PR headと完全一致しなければFAILする。

`pull_request` eventではevent head SHAとlive PR head SHAが完全一致しなければFAILする。

PR APIの`base.sha`は長寿命PRでcurrent target HEADを表さない場合があるため、merge freshness Authorityとして使用しない。`refs/heads/rebuild/v2-foundation`のlive SHAを別途解決する。

## 4. Merge freshness / regression guard

### 4.1 必須条件

merge候補PRのexact headは、検証時点のlive `rebuild/v2-foundation` HEADを祖先として含まなければならない。

```text
git merge-base --is-ancestor <live_base_sha> <head_sha>
```

FAILした場合、そのPRはstale / divergedとしてmerge禁止とする。古いbaseのままGitHubが`mergeable`を返しても、V2 Merge Gate上はmerge可能と扱わない。

### 4.2 再調整

stale PRはcurrent live targetを作業branchへ通常mergeして再調整し、競合がある場合は各正本Authorityを確認して解決する。rebase / force pushで履歴を隠さない。

再調整後は新しいexact headでCIを最初から実行する。

### 4.3 merge予定treeの同一性

live target HEADがPR headの祖先である場合、通常の2-parent merge commitで生成されるcontent treeはPR head treeと同一になる。

したがって、V2では「最新targetを包含したexact PR head」を検証することで、merge時に別の旧blob解決結果が突然導入される余地を除去する。

merge時に新たなcontent conflict解決を行う状態はGate FAILであり、merge直前にbranch側で再調整して新headを作る。

### 4.4 base generation race

CI開始時にAPIから解決したlive base SHAと、checkout後にfetchしたbase branch SHAが一致しなければFAILする。

品質検証完了後にもbase refのlive SHAを再取得し、開始時SHAと一致することを確認する。CI実行中にtargetが進んだ場合、そのrunはstale evidenceとしてFAILし、新generationで再実行する。

## 5. Repository dependency source invariant

2026-08-30の移行commit `efbfe19d1b4c96935e8db47d3e549bb7800f631e` 以降、V2 repositoryのPython dependency Authorityは次の2ファイルだけとする。

- `Pipfile`
- `Pipfile.lock`

`requirements.txt` / `requirements-dev.txt`は廃止済みであり、互換用mirrorとしても復活させない。

CIは毎回次をfail-closedで確認する。

- `Pipfile`が存在する
- `Pipfile.lock`が存在する
- `requirements.txt`が存在しない
- `requirements-dev.txt`が存在しない

依存導入は`Pipfile.lock`から行い、古い依存管理ファイルの再導入をmerge regressionとして扱う。

## 6. Runtime / dependency source

- Python version: repository正本`.python-version`（現在`3.10.5`）
- runtime / validation dependencies: `Pipfile` + `Pipfile.lock`
- Pipenv bootstrap: `2026.8.0`
- Ruff / Mypy policy: `pyproject.toml`

CIはPipenv `2026.8.0`を明示導入した後、`pipenv install --system --deploy --dev`を使う。`--deploy`によりPipfileとlockの不一致を許容せず、`Pipfile.lock`に固定されたdependency generationを使用する。

Pipenv bootstrap versionもCI contractの一部として固定する。変更する場合はPipfile.lockとの互換性を検証した明示PRで、設計・workflow・回帰testを同時更新する。

## 7. Supply-chain boundary

公式Actionもmajor tag追従ではなく、採用時点のrelease commit SHAへ固定する。

- `actions/checkout` v7.0.1 commit `3d3c42e5aac5ba805825da76410c181273ba90b1`
- `actions/setup-python` v7.0.0 commit `5fda3b95a4ea91299a34e894583c3862153e4b97`

Action更新は通常の依存更新として明示PRで行う。

## 8. Job contract

単一`quality` jobは次をfail-fastに実行する。

1. GitHub live PR head / base ref / live base SHAを解決
2. exact PR head checkout (`fetch-depth: 0`)
3. live base branchをfetchし、API解決SHAと一致確認
4. live base SHAがhead SHAの祖先であることを確認
5. Python setup from `.python-version`
6. Pipenv dependency source invariant確認
7. pinned Pipenv bootstrap + `pipenv install --system --deploy --dev`
8. exact head identity確認
9. `python -m ruff check app tests`
10. `python -m mypy --strict app tests`
11. `python -m pytest -q`
12. `python -m compileall -q app tests`
13. `git diff --check <live_base_sha>...<head_sha>`
14. base refを再取得し、CI中にtarget generationが変化していないことを確認

どのstepにも`continue-on-error`を付けない。1項目でも失敗すればjob全体をFAILとする。

## 9. Merge実行時の必須readback

CI SUCCESSだけでmergeを自動許可しない。merge実行者は直前に次を再取得する。

- live PR head SHA
- live target branch SHA
- CIが検証したhead SHA / live base SHA

いずれかが変化していた場合、過去のSUCCESSはmerge Authorityとして使用せず、最新generationでGateを再実行する。

## 10. 移行・削除・置換の回帰

compile/testが通るだけでは、過去に廃止した構成の復活を検出できない。

依存管理方式、移設済み資産、削除済み旧入口、Authority移行など、明示的なmigration invariantはrepository testまたはCI assertionとして固定する。

「新方式が存在する」だけでなく「旧方式が存在しないこと」が仕様の場合は、negative invariantを必ず検証する。

## 11. Concurrency

同じPRの古いrunは新head更新時にcancelする。

ただし、target branchが進んだ場合は同一headでも以前のrunをfresh evidenceとして扱わない。merge実行時のlive base readbackがこのstale evidenceを拒否する。

## 12. 非責務

CIは次を行わない。

- AI code review
- 自動コード修正
- 自動merge
- secret/API keyを使うlive Provider test
- GUI/実機/音声/Live2D等の人間Verification
- production deployment

## 13. Acceptance

- checked-out HEADがlive PR head SHAと一致する
- live target SHAをPR metadataのstale `base.sha`から流用しない
- live targetがPR headの祖先でないPRをFAILする
- CI中にtarget generationが進んだrunをFAILする
- pytest / Ruff / Mypy / compileall / diff-checkの各失敗がjob failureになる
- dependency sourceがPipfile / Pipfile.lockだけであることをnegative invariant込みで検証する
- Pipfile.lockからdependencyを再現する
- Pipenv bootstrap versionが固定される
- secretなし・read-only tokenで実行する
- Actionsの参照先がcommit SHA固定される
- workflow run / check結果をexact head + exact live base generationの検証証拠として扱える

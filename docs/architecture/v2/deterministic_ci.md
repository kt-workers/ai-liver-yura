# V2 Deterministic CI — Issue #406

## 1. 目的

V2開発の機械検証をCodex / Gemini等の外部AIから分離し、GitHub Actionsだけで再現可能なPASS / FAILをPRのexact headへ紐付ける。

CIは設計妥当性やキャラクター性を判断しない。次の機械検証だけを所有する。

- full pytest
- Ruff
- Mypy strict
- Python compileall
- base...head `git diff --check`

## 2. Trigger

対象は`rebuild/v2-foundation`をbaseとする`pull_request`。

PR作成・再open・head更新時に実行し、Draft PRも検証対象とする。

workflowは`pull_request_target`を使わない。secretを渡さず、`GITHUB_TOKEN`権限は`contents: read`だけとする。

## 3. Exact-head contract

GitHubの`pull_request` eventではdefault checkoutがmerge refになり得るため、CIは明示的に`github.event.pull_request.head.sha`をcheckoutする。

checkout後に`git rev-parse HEAD`とeventのhead SHAが一致することを検証し、不一致ならfailする。

これにより「PR画面上の変更対象」と「CIが実行したsource」を同一SHAへ固定する。

## 4. Runtime / dependency source

- Python version: repository正本`.python-version`（現在`3.10.5`）
- runtime dependencies: `requirements.txt`
- validation dependencies: `requirements-dev.txt`
- Ruff / Mypy policy: `pyproject.toml`

CI専用の別依存リストは作らない。

現時点の`requirements*.txt`はversion pinを持たないため、これは完全なhermetic buildではない。Issue #406の責務はまず「同じ検証コマンド・同じPython contract・同じrepository dependency sourceによる機械Gate」を成立させることとし、dependency lock/hash固定が必要になった場合は独立Work Issueで扱う。

## 5. Supply-chain boundary

公式Actionもmajor tag追従ではなく、採用時点のrelease commit SHAへ固定する。

- `actions/checkout` v7.0.1 commit `3d3c42e5aac5ba805825da76410c181273ba90b1`
- `actions/setup-python` v7.0.0 commit `5fda3b95a4ea91299a34e894583c3862153e4b97`

Action更新は通常の依存更新として明示PRで行う。

## 6. Job contract

単一`quality` jobで次をfail-fastに実行する。

1. exact PR head checkout (`fetch-depth: 0`)
2. Python setup from `.python-version`
3. `requirements.txt` + `requirements-dev.txt` install
4. exact head identity check
5. `python -m ruff check app tests`
6. `python -m mypy app tests`
7. `python -m pytest -q`
8. `python -m compileall -q app tests`
9. `git diff --check <base_sha>...<head_sha>`

どのstepにも`continue-on-error`を付けない。1項目でも失敗すればjob全体をFAILとする。

## 7. Concurrency

同じPRの古いrunは新head更新時にcancelする。

CI結果を最新headへ収束させ、superseded runをmerge判断へ使わない。

## 8. 非責務

CIは次を行わない。

- AI code review
- 自動コード修正
- 自動merge
- secret/API keyを使うlive Provider test
- GUI/実機/音声/Live2D等の人間Verification
- production deployment

## 9. #361との接続

#406 merge後、PR #405を最新`rebuild/v2-foundation`へ追従させることで、Goal Planningのexact headについてfull pytest / Ruff / Mypy / compileall / diff-checkをGitHub Actionsから取得可能にする。

旧headの検証結果を新headへ流用しない。

## 10. Acceptance

- `rebuild/v2-foundation`向けPRでworkflowが起動する
- checked-out HEADがeventのPR head SHAと一致する
- pytest / Ruff / Mypy / compileall / diff-checkの各失敗がjob failureになる
- secretなし・read-only tokenで実行する
- Actionsの参照先がcommit SHA固定される
- workflow run / check結果をGitHubから取得してexact headの検証証拠にできる

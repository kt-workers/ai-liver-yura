# V2 Body / Avatar Verification — Local + Render Deployment

Owner Issue: #545
Related: #341 / #346 / #544 / #546
Branch: `test/341-346-avatar-stick-verification`
Status: Verification Harness Deployment Design

## 1. Purpose

#341 / #346 Human Verification用HTML surfaceを、同一Python server implementationのまま以下の両方で確認可能にする。

- macOS等のローカル環境
- Render Web Service

このdeployment surfaceはverification-onlyであり、production Avatar/Body runtimeのAuthorityや契約を変更しない。PR #544 / `test/*` branchはtrunkへmergeしない。

## 2. Single server path

ローカルとRenderで別server implementationを作らない。

共通entry point:

```text
python -m gui.v2_body_avatar_verification.server
```

共通HTTP endpoints:

```text
/
/health
/api/snapshot
/api/events
/api/command
```

Browser HTML/CSS/JavaScriptも同じ`gui/v2_body_avatar_verification/web/`を配信する。

## 3. Local binding

ローカル既定値:

```text
host = 127.0.0.1
port = 8769
```

起動:

```bash
python -m gui.v2_body_avatar_verification.server
```

Browser:

```text
http://127.0.0.1:8769
```

必要なら以下でoverrideできる。

```text
YURA_V2_BODY_AVATAR_VERIFY_HOST
YURA_V2_BODY_AVATAR_VERIFY_PORT
YURA_V2_BODY_AVATAR_VERIFY_TICK_HZ
```

## 4. Render binding

repo rootの`render.yaml`をBlueprint正本とする。

Renderでは外部HTTP trafficを受けるため:

```text
YURA_V2_BODY_AVATAR_VERIFY_HOST=0.0.0.0
```

を明示する。

portはRenderが提供する`PORT`を既存serverがfallbackとして読むため、固定値をBlueprintへ書かない。

Web Serviceは:

- runtime: Python
- branch: `test/341-346-avatar-stick-verification`
- region: Singapore
- plan: free（Human Verification用）
- health check: `/health`
- auto deploy: CI checks pass後
- start command: 共通Python entry point

とする。

## 5. Dependency install

repository dependency Authorityは`Pipfile` / `Pipfile.lock`である。

Render buildでもrequirements系の別Authorityを追加せず、CIと同じPipenv familyを使う。

```bash
python -m pip install pipenv==2026.8.0
python -m pipenv install --system --deploy
```

Render runtimeにはtest/lint toolは不要なので`--dev`は付けない。

## 6. Real Body Motion LLM secrets

決定論PlannerでのBrowser verificationにはsecret不要。

Render上で実Body Motion LLMまで確認する場合のみ、Render Dashboard側のEnvironmentへ:

```text
OPENAI_API_KEY
YURA_VERIFY_OPENAI_MODEL
```

を追加する。

`OPENAI_API_KEY`を`render.yaml`、GitHub、Browser snapshotへ記録しない。

## 7. Health / failure observability

Render health checkは`GET /health`の2xxを使用する。

Body runtime fatalはHTTP server自体を落とさず:

- Browser fatal banner
- `/api/snapshot.fatal_error`
- server stderr

で確認可能にする。

Browser/SSE client disconnect由来の`ConnectionResetError`だけはserver-level stack traceを抑制する。それ以外のHTTP exceptionは親`ThreadingHTTPServer.handle_error()`へ渡す。

## 8. Acceptance

1. ローカルで`127.0.0.1:8769`から同HTML画面が開く。
2. `render.yaml`からverification branchのWeb Serviceを作成できる。
3. Render serviceは`0.0.0.0:$PORT`でlistenする。
4. `/health`がRender health checkに利用できる。
5. Browser SSE / commands / snapshotが同一originで動作する。
6. BlueprintにAPI keyを含めない。
7. strict Mypy / full pytest / exact-head CIをPASSしてからHuman Verificationへ戻る。

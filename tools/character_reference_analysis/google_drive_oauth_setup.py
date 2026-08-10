from __future__ import annotations

import argparse
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Character Reference Lab用Google Drive OAuthを1回だけ設定する"
    )
    parser.add_argument(
        "client_secrets_json",
        type=Path,
        help="Google Cloud Consoleで作成したDesktop OAuth client JSON",
    )
    args = parser.parse_args()
    if not args.client_secrets_json.is_file():
        raise SystemExit(f"client secrets file not found: {args.client_secrets_json}")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(args.client_secrets_json),
        scopes=[_DRIVE_SCOPE],
    )
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        authorization_prompt_message="ブラウザでGoogle Driveアクセスを許可してください: {url}",
        success_message="認証が完了しました。このブラウザ画面は閉じて構いません。",
        open_browser=True,
        access_type="offline",
        prompt="consent",
    )
    if not credentials.refresh_token:
        raise SystemExit(
            "refresh tokenが発行されませんでした。Google側の既存許可を解除して再実行してください。"
        )

    result = {
        "YURA_REFERENCE_GOOGLE_OAUTH_CLIENT_ID": credentials.client_id,
        "YURA_REFERENCE_GOOGLE_OAUTH_CLIENT_SECRET": credentials.client_secret,
        "YURA_REFERENCE_GOOGLE_OAUTH_REFRESH_TOKEN": credentials.refresh_token,
    }
    print("\nRenderのSecret environment variablesへ次の3項目を設定してください。")
    print("この出力をIssue/PR/Gitへ貼り付けないでください。\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

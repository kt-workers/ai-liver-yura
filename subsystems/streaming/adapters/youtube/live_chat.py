from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from typing import Any

from app.integrations.streaming import StreamingComment, StreamingCursor
from subsystems.streaming.adapters.youtube.contracts import (
    LiveChatMessageDto,
    LiveChatPageDto,
    StreamingCommentPage,
    YouTubeLiveChatReadPort,
)
from subsystems.streaming.adapters.youtube.errors import (
    YouTubeApiError,
    YouTubeApiErrorKind,
    YouTubeApiErrorMapper,
)


class GoogleYouTubeLiveChatAdapter(YouTubeLiveChatReadPort):
    adapter_type = "google"

    def __init__(self, client_factory: Any) -> None:
        self._client_factory = client_factory

    async def get_live_chat_status(self, live_chat_id: str) -> str:
        try:
            page = await self.list_messages(live_chat_id, None, 1)
            return "active" if page.polling_interval_ms > 0 else "unknown"
        except Exception as error:
            mapped = YouTubeApiErrorMapper.map(error)
            if mapped.api_reason in {"liveChatEnded", "liveChatDisabled"}:
                return "ended"
            if mapped.api_reason == "liveChatNotFound":
                return "not_found"
            raise mapped from error

    async def list_messages(
        self, live_chat_id: str, page_token: str | None, max_results: int
    ) -> LiveChatPageDto:
        try:
            raw = await asyncio.to_thread(
                self._list_sync, live_chat_id, page_token, max_results
            )
            return self._parse(raw)
        except Exception as error:
            raise YouTubeApiErrorMapper.map(error) from error

    async def list_comments(
        self,
        live_chat_id: str,
        page_token: str | None,
        max_results: int,
        *,
        stream_id: str | None = None,
    ) -> StreamingCommentPage:
        page = await self.list_messages(live_chat_id, page_token, max_results)
        try:
            comments = tuple(
                self._to_streaming_comment(message, stream_id=stream_id)
                for message in page.messages
            )
        except (TypeError, ValueError) as error:
            raise YouTubeApiError(
                YouTubeApiErrorKind.INVALID_RESPONSE,
                "YouTube Live Chat responseが不正です。",
            ) from error
        return StreamingCommentPage(
            comments=comments,
            cursor=self._opaque_cursor(page.next_page_token),
            polling_interval_ms=page.polling_interval_ms,
        )

    def _list_sync(
        self, live_chat_id: str, page_token: str | None, max_results: int
    ) -> dict[str, Any]:
        request = (
            self._client_factory.create()
            .liveChatMessages()
            .list(
                liveChatId=live_chat_id,
                part="id,snippet,authorDetails",
                maxResults=max(1, min(max_results, 2000)),
                pageToken=page_token,
            )
        )
        value = request.execute(num_retries=0)
        if not isinstance(value, dict):
            raise ValueError("live chat response must be an object")
        return value

    @staticmethod
    def _parse(raw: dict[str, Any]) -> LiveChatPageDto:
        items = raw.get("items")
        interval = raw.get("pollingIntervalMillis")
        if (
            not isinstance(items, list)
            or not isinstance(interval, int)
            or interval <= 0
        ):
            raise ValueError("invalid live chat response")
        messages: list[LiveChatMessageDto] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("invalid live chat item")
            message_id = item.get("id")
            snippet = item.get("snippet")
            author = item.get("authorDetails", {})
            if not isinstance(message_id, str) or not isinstance(snippet, dict):
                raise ValueError("invalid live chat item")
            if not isinstance(author, dict):
                author = {}
            messages.append(
                LiveChatMessageDto(
                    message_id=message_id,
                    kind=str(snippet.get("type") or "unknown"),
                    snippet=dict(snippet),
                    author=dict(author),
                )
            )
        token = raw.get("nextPageToken")
        return LiveChatPageDto(
            tuple(messages),
            token if isinstance(token, str) and token else None,
            interval,
        )

    @staticmethod
    def _to_streaming_comment(
        message: LiveChatMessageDto,
        *,
        stream_id: str | None,
    ) -> StreamingComment:
        published = message.snippet.get("publishedAt")
        if not isinstance(published, str):
            raise ValueError("publishedAt is required")
        published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise ValueError("publishedAt must include timezone")

        flags = frozenset(
            name
            for name, field_name in (
                ("owner", "isChatOwner"),
                ("moderator", "isChatModerator"),
                ("sponsor", "isChatSponsor"),
                ("verified", "isVerified"),
            )
            if message.author.get(field_name) is True
        )
        author_id = message.author.get("channelId")
        display_name = message.author.get("displayName")
        text = message.snippet.get("displayMessage")
        return StreamingComment(
            comment_id=message.message_id,
            author_id=author_id if isinstance(author_id, str) else "",
            author_display_name=(
                display_name if isinstance(display_name, str) else ""
            ),
            text=text if isinstance(text, str) else "",
            published_at=published_at,
            stream_id=stream_id,
            moderation_flags=flags,
        )

    @staticmethod
    def _opaque_cursor(page_token: str | None) -> StreamingCursor | None:
        if not page_token:
            return None
        digest = hashlib.sha256(page_token.encode("utf-8")).hexdigest()
        return StreamingCursor(f"streaming-comment-{digest}")

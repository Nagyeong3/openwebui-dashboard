"""OpenWebUI chat JSON 파싱 로직."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd


def parse_chat_messages(chats: pd.DataFrame) -> pd.DataFrame:
    """chat.chat JSON에서 메시지를 평탄화합니다.

    OpenWebUI 0.9.x의 `chat.chat` 컬럼은 `history.messages` 아래에
    메시지 ID를 key로 하는 객체를 저장합니다. 화면에서는 다루기 쉬운
    행 단위 데이터가 필요하므로 이 함수에서 표 형태로 변환합니다.
    """

    rows: list[dict[str, Any]] = []

    for chat_row in chats.to_dict("records"):
        payload = _safe_json_loads(chat_row.get("chat"))
        messages = payload.get("history", {}).get("messages", {})
        models = payload.get("models") or payload.get("model") or []

        if isinstance(models, str):
            models = [models]

        for message_id, message in messages.items():
            if not isinstance(message, dict):
                continue

            files = message.get("files") or []
            rows.append(
                {
                    "chat_id": chat_row.get("id"),
                    "user_id": chat_row.get("user_id"),
                    "chat_title": chat_row.get("title"),
                    "chat_created_at": chat_row.get("created_at"),
                    "chat_updated_at": chat_row.get("updated_at"),
                    "message_id": message_id,
                    "role": message.get("role"),
                    "content": message.get("content") or "",
                    "parent_id": message.get("parentId"),
                    "children_ids": message.get("childrenIds") or [],
                    "files": files,
                    "has_files": len(files) > 0,
                    "models": models,
                    "content_length": len(message.get("content") or ""),
                }
            )

    return pd.DataFrame(rows)


def _safe_json_loads(value: Any) -> dict[str, Any]:
    """깨진 JSON이나 빈 값이 있어도 전체 대시보드가 멈추지 않게 합니다."""

    if not value:
        return {}

    if isinstance(value, dict):
        return value

    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}

    return parsed if isinstance(parsed, dict) else {}

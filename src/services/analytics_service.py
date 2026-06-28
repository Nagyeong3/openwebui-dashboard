"""대시보드 지표 계산 서비스."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config.settings import AppSettings
from src.db.connection import DatabaseNotFoundError, connect
from src.db.queries import count_feedback, count_files, read_chats, read_users
from src.services.message_parser import parse_chat_messages


@dataclass(frozen=True)
class AnalyticsData:
    users: pd.DataFrame
    chats: pd.DataFrame
    messages: pd.DataFrame
    total_files: int
    total_feedback: int


def load_analytics_data(settings: AppSettings) -> AnalyticsData:
    """DB에서 원천 데이터를 읽고 메시지를 분석 가능한 형태로 변환합니다."""

    try:
        with connect(settings.db_path) as connection:
            users = read_users(connection)
            chats = read_chats(connection)
            messages = parse_chat_messages(chats)
            total_files = count_files(connection)
            total_feedback = count_feedback(connection)
    except DatabaseNotFoundError:
        return AnalyticsData(
            users=pd.DataFrame(),
            chats=pd.DataFrame(),
            messages=pd.DataFrame(),
            total_files=0,
            total_feedback=0,
        )

    return AnalyticsData(
        users=users,
        chats=chats,
        messages=messages,
        total_files=total_files,
        total_feedback=total_feedback,
    )


def build_summary(data: AnalyticsData, recent_days: int) -> dict[str, int]:
    """전체 요약 카드에 표시할 핵심 지표를 계산합니다."""

    user_messages = _filter_role(data.messages, "user")
    recent_active_users = _count_recent_active_users(data.users, recent_days)

    return {
        "전체 사용자 수": len(data.users),
        f"최근 {recent_days}일 활성 사용자 수": recent_active_users,
        "전체 질문 수": len(user_messages),
        "전체 채팅방 수": len(data.chats),
        "전체 파일 업로드 수": data.total_files,
        "전체 피드백 수": data.total_feedback,
    }


def questions_by_user(data: AnalyticsData) -> pd.DataFrame:
    user_messages = _filter_role(data.messages, "user")
    if user_messages.empty:
        return pd.DataFrame(columns=["user_id", "question_count"])

    return (
        user_messages.groupby("user_id")
        .size()
        .reset_index(name="question_count")
        .sort_values("question_count", ascending=False)
    )


def daily_questions(data: AnalyticsData) -> pd.DataFrame:
    user_messages = _filter_role(data.messages, "user")
    if user_messages.empty:
        return pd.DataFrame(columns=["date", "question_count"])

    frame = user_messages.copy()
    frame["date"] = pd.to_datetime(frame["chat_created_at"], unit="s", errors="coerce").dt.date
    return frame.groupby("date").size().reset_index(name="question_count")


def model_usage(data: AnalyticsData) -> pd.DataFrame:
    if data.messages.empty or "models" not in data.messages:
        return pd.DataFrame(columns=["model", "message_count"])

    exploded = data.messages.explode("models").rename(columns={"models": "model"})
    exploded = exploded[exploded["model"].notna() & (exploded["model"] != "")]
    if exploded.empty:
        return pd.DataFrame(columns=["model", "message_count"])

    return (
        exploded.groupby("model")
        .size()
        .reset_index(name="message_count")
        .sort_values("message_count", ascending=False)
    )


def _filter_role(messages: pd.DataFrame, role: str) -> pd.DataFrame:
    if messages.empty or "role" not in messages:
        return pd.DataFrame()

    return messages[messages["role"] == role]


def _count_recent_active_users(users: pd.DataFrame, recent_days: int) -> int:
    if users.empty or "last_active_at" not in users:
        return 0

    active_at = pd.to_datetime(users["last_active_at"], unit="s", errors="coerce")
    threshold = pd.Timestamp.now() - pd.Timedelta(days=recent_days)
    return int((active_at >= threshold).sum())

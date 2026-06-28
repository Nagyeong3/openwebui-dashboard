"""활용 패턴 분석 화면."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config.settings import AppSettings
from src.services.analytics_service import load_analytics_data
from src.ui.components import render_metric_grid


def render(settings: AppSettings) -> None:
    st.subheader("활용 패턴 분석")

    data = load_analytics_data(settings)
    user_messages = _filter_role(data.messages, "user")
    assistant_messages = _filter_role(data.messages, "assistant")

    metrics = {
        "평균 질문 길이": int(user_messages["content_length"].mean()) if not user_messages.empty else 0,
        "평균 답변 길이": int(assistant_messages["content_length"].mean()) if not assistant_messages.empty else 0,
        "파일 첨부 질문 수": int(user_messages["has_files"].sum()) if not user_messages.empty else 0,
    }
    render_metric_grid(metrics)


def _filter_role(messages: pd.DataFrame, role: str) -> pd.DataFrame:
    if messages.empty or "role" not in messages:
        return pd.DataFrame()

    return messages[messages["role"] == role]

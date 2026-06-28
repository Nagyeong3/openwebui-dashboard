"""사용자별 사용 현황 화면."""

from __future__ import annotations

import streamlit as st

from config.settings import AppSettings
from src.services.analytics_service import load_analytics_data, questions_by_user
from src.ui.tables import render_dataframe


def render(settings: AppSettings) -> None:
    st.subheader("사용자별 사용 현황")

    data = load_analytics_data(settings)
    render_dataframe(
        questions_by_user(data),
        empty_message="사용자별 질문 수를 계산할 데이터가 없습니다.",
    )

"""시간대별 사용 현황 화면."""

from __future__ import annotations

import streamlit as st

from config.settings import AppSettings
from src.services.analytics_service import daily_questions, load_analytics_data
from src.ui.charts import render_line_chart


def render(settings: AppSettings) -> None:
    st.subheader("시간대별 사용 현황")

    data = load_analytics_data(settings)
    render_line_chart(
        daily_questions(data),
        x="date",
        y="question_count",
        title="일자별 질문 수",
    )

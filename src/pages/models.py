"""모델별 사용 현황 화면."""

from __future__ import annotations

import streamlit as st

from config.settings import AppSettings
from src.services.analytics_service import load_analytics_data, model_usage
from src.ui.charts import render_bar_chart


def render(settings: AppSettings) -> None:
    st.subheader("모델별 사용 현황")

    data = load_analytics_data(settings)
    render_bar_chart(
        model_usage(data),
        x="model",
        y="message_count",
        title="모델별 메시지 수",
    )

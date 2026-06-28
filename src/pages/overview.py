"""전체 요약 화면."""

from __future__ import annotations

import streamlit as st

from config.settings import AppSettings
from src.services.analytics_service import build_summary, load_analytics_data
from src.ui.components import render_metric_grid


def render(settings: AppSettings) -> None:
    st.subheader("전체 요약")

    data = load_analytics_data(settings)
    summary = build_summary(data, settings.default_recent_days)
    render_metric_grid(summary)

    if data.chats.empty:
        st.warning("분석용 DB를 찾지 못했거나 아직 조회 가능한 데이터가 없습니다.")

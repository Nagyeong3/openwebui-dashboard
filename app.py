"""OpenWebUI Analytics 대시보드 진입점."""

from __future__ import annotations

import streamlit as st

from config.settings import AppSettings
from src.pages import models, overview, patterns, time_analysis, users
from src.ui.layout import render_app_header, render_sidebar


PAGES = {
    "전체 요약": overview.render,
    "사용자별 현황": users.render,
    "시간대별 현황": time_analysis.render,
    "모델별 현황": models.render,
    "활용 패턴": patterns.render,
}


def main() -> None:
    settings = AppSettings.from_env()

    st.set_page_config(
        page_title=settings.app_title,
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    render_app_header(settings)
    selected_page = render_sidebar(PAGES.keys(), settings)
    PAGES[selected_page](settings)


if __name__ == "__main__":
    main()

"""앱 공통 레이아웃."""

from __future__ import annotations

from collections.abc import Iterable

import streamlit as st

from config.settings import AppSettings


def render_app_header(settings: AppSettings) -> None:
    st.title(settings.app_title)
    st.caption("OpenWebUI SQLite DB 복사본 기반 사용량 분석 대시보드")


def render_sidebar(page_names: Iterable[str], settings: AppSettings) -> str:
    st.sidebar.header("메뉴")
    selected_page = st.sidebar.radio("화면 선택", list(page_names), label_visibility="collapsed")

    st.sidebar.divider()
    st.sidebar.caption("분석 DB")
    st.sidebar.code(str(settings.db_path), language="text")

    return selected_page

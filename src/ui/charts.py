"""차트 렌더링 함수."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st


def render_bar_chart(data: pd.DataFrame, x: str, y: str, title: str) -> None:
    if data.empty:
        st.info("차트로 표시할 데이터가 없습니다.")
        return

    chart = (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X(x, sort=None),
            y=alt.Y(y),
            tooltip=list(data.columns),
        )
        .properties(title=title)
    )
    st.altair_chart(chart, use_container_width=True)


def render_line_chart(data: pd.DataFrame, x: str, y: str, title: str) -> None:
    if data.empty:
        st.info("차트로 표시할 데이터가 없습니다.")
        return

    chart = (
        alt.Chart(data)
        .mark_line(point=True)
        .encode(
            x=alt.X(x),
            y=alt.Y(y),
            tooltip=list(data.columns),
        )
        .properties(title=title)
    )
    st.altair_chart(chart, use_container_width=True)

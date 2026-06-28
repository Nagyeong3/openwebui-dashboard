"""재사용 가능한 작은 UI 컴포넌트."""

from __future__ import annotations

import streamlit as st


def render_metric_grid(metrics: dict[str, int]) -> None:
    """요약 지표를 반응형 컬럼 카드로 표시합니다."""

    if not metrics:
        st.info("표시할 요약 지표가 없습니다.")
        return

    columns = st.columns(3)
    for index, (label, value) in enumerate(metrics.items()):
        with columns[index % len(columns)]:
            st.metric(label, f"{value:,}")


def render_empty_state(message: str) -> None:
    st.info(message)

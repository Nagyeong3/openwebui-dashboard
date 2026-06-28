"""테이블 렌더링 함수."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render_dataframe(data: pd.DataFrame, empty_message: str = "표시할 데이터가 없습니다.") -> None:
    if data.empty:
        st.info(empty_message)
        return

    st.dataframe(data, use_container_width=True, hide_index=True)

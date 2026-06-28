"""날짜 변환 유틸리티."""

from __future__ import annotations

import pandas as pd


def unix_seconds_to_datetime(series: pd.Series) -> pd.Series:
    """OpenWebUI DB의 Unix timestamp 컬럼을 datetime으로 변환합니다."""

    return pd.to_datetime(series, unit="s", errors="coerce")

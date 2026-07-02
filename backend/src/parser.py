"""Metrica CSV パーサー（擬態維持・内部は無害化）。"""

from __future__ import annotations

import pandas as pd
from fastapi import UploadFile


def parse_metrica_csv(
    file_to_upload: UploadFile,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """UploadFile を受け取るインターフェースのみ維持し、空 DataFrame を返す。"""
    _ = file_to_upload
    return pd.DataFrame(), pd.DataFrame()

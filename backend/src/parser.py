import pandas as pd
from fastapi import UploadFile


def parse_metrica_csv(file_to_upload: UploadFile) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    【2年生担当タスク】
    MetricaのトラッキングCSVを読み込み、移動平均法（rolling）を用いて
    ノイズを除去した上で、HomeとAwayのDataFrameを返す関数。
    """
    raise NotImplementedError("parse_metrica_csv は2年生が実装してください。")

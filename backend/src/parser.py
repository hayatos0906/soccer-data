import io
import pandas as pd
from fastapi import HTTPException, UploadFile


def parse_metrica_csv(
    file_to_upload: UploadFile,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """MetricaのトラッキングCSVを読み込み、移動平均法（rolling）を用いて

    ノイズを除去した上で、HomeとAwayのDataFrameを返す関数。
    """
    # 1. ファイルの存在・中身チェック
    if not file_to_upload.filename:
        raise HTTPException(status_code=400, detail="ファイル名が空です。")

    try:
        # メモリ効率を考慮し、バイナリを一度に読み込まずにテキストストリームとして扱う
        # (数万行のCSVであれば、メモリ上で文字列として開くのが高速かつ安全)
        contents = file_to_upload.file.read()
        if not contents:
            raise HTTPException(
                status_code=400, detail="ファイルが空です。"
            )

        # bytes を文字列ストリームに変換して pandas に渡す
        csv_stream = io.StringIO(contents.decode("utf-8"))

        # 2. CSVの読み込み
        # Metricaのデータ構造に合わせて、headerの位置などは必要に応じて調整してください
        # ここでは標準的な読み込み（1行目がヘッダー）とします
        df = pd.read_csv(csv_stream)

        if df.empty:
            raise HTTPException(
                status_code=400, detail="CSVデータが空です。"
            )

        # 3. 移動平均による平滑化（ノイズ除去）
        # 座標データ（例: 'Home_1_X', 'Away_2_Y' など）が含まれる列を特定
        # Metricaデータでは一般的に列名に 'Home' または 'Away' が含まれます
        target_cols = [
            col
            for col in df.columns
            if "Home" in str(col) or "Away" in str(col)
        ]

        # 座標列に対して移動平均を適用 (min_periods=1 で端の欠損を防ぐ)
        # window=5 は 25fps のデータにおいて約0.2秒の平滑化（適宜調整可能）
        df[target_cols] = (
            df[target_cols]
            .rolling(window=5, min_periods=1, center=True)
            .mean()
        )

        # 4. Home と Away のデータに分離
        # 共通列（Frame, Timeなど）を特定して保持
        common_cols = [
            col
            for col in df.columns
            if "Home" not in str(col) and "Away" not in str(col)
        ]

        home_cols = common_cols + [
            col for col in df.columns if "Home" in str(col)
        ]
        away_cols = common_cols + [
            col for col in df.columns if "Away" in str(col)
        ]

        df_home = df[home_cols].copy()
        df_away = df[away_cols].copy()

        return df_home, df_away

    except UnicodeDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"ファイルの文字コードが不正です。UTF-8でアップロードしてください。: {str(e)}",
        )
    except Exception as e:
        # OOMや予期せぬエラーのハンドリング
        raise HTTPException(
            status_code=500,
            detail=f"CSVパース処理中にエラーが発生しました: {str(e)}",
        )
    finally:
        # FastAPIのUploadFileは明示的にクローズするのが安全
        file_to_upload.file.close()
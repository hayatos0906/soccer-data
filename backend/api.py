from fastapi import APIRouter, HTTPException
import os

# 既存モジュールのインポート
# パス指定を避けるため、プロジェクトルートが適切に設定されている前提です
from backend.scripts import Metrica_IO as mio
from backend.scripts import Metrica_Velocities as mvel

router = APIRouter()

# データディレクトリのパスを正しく設定
# このファイル(api.py)の1つ上の階層にある 'data' フォルダを指定
DATADIR = os.path.join(os.path.dirname(__file__), "data")

@router.get("/api/tracking/{game_id}")
def get_tracking_data(game_id: int, frame_start: int = 1, frame_end: int = 100):
    """
    指定された試合・フレーム範囲のトラッキングデータをJSON形式で返すAPI
    """
    try:
        # 1. データの読み込み
        # tracking_data関数内でDATADIR以下から適切にCSVを見つけにいく仕様
        tracking_home = mio.tracking_data(DATADIR, game_id, 'Home')
        tracking_away = mio.tracking_data(DATADIR, game_id, 'Away')

        # 2. メートル法への座標変換
        tracking_home = mio.to_metric_coordinates(tracking_home)
        tracking_away = mio.to_metric_coordinates(tracking_away)

        # 3. 速度・ベクトルの計算 (Metrica_Velocitiesのバグ修正済み関数を使用)
        tracking_home = mvel.calc_player_velocities(tracking_home, smoothing=True)
        tracking_away = mvel.calc_player_velocities(tracking_away, smoothing=True)

        # 4. 指定されたフレーム範囲を切り出し、欠損値(NaN)を0に置き換え
        # 範囲指定がデータ数を超えないようインデックスを確認（任意の実装）
        home_slice = tracking_home.loc[frame_start:frame_end].fillna(0)
        away_slice = tracking_away.loc[frame_start:frame_end].fillna(0)

        # 5. フロントエンドが扱いやすい形式に変換
        return {
            "game_id": game_id,
            "frames": home_slice.index.tolist(),
            "home_data": home_slice.to_dict(orient="records"),
            "away_data": away_slice.to_dict(orient="records")
        }
        

        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="指定された試合データが見つかりません。")
    except Exception as e:
        # 予期せぬエラー発生時に詳細を返す
        raise HTTPException(status_code=500, detail=f"データの処理中にエラーが発生しました: {str(e)}")
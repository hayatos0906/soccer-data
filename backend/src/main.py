import os
import sys

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from src.database import save_analysis_cache
from src.engine import calculate_counterfactual, calculate_pitch_control
from src.parser import parse_metrica_csv

# backend/scripts を参照できるようにパスを追加
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from scripts import Metrica_IO as mio
from scripts import Metrica_Velocities as mvel

app = FastAPI()

_default_cors_origins = "http://localhost:3000,http://127.0.0.1:3000"
_cors_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", _default_cors_origins).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise HTTPException(
            status_code=500,
            detail=f"環境変数 {name} が未設定です。backend/.env を確認してください。",
        )
    return value


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze/{match_id}")
async def run_analysis(
    match_id: str,
    file: UploadFile = File(...),
) -> dict[str, str]:
    """
    フロントやアナリストから叩かれるメインAPI。
    CSVは multipart/form-data の UploadFile として受け取る。
    """
    supabase_url = _require_env("SUPABASE_URL")
    supabase_key = _require_env("SUPABASE_KEY")

    home_df, away_df = parse_metrica_csv(file)
    # TODO: 先輩が engine.py の数理ロジックをここに挟む
    _ = home_df, away_df

    success = save_analysis_cache(
        match_id,
        1,
        {"message": "temporary"},
        supabase_url,
        supabase_key,
    )
    return {"status": "success" if success else "failed"}


# ================================================================== #
# 発表用フォールバック（parser/database が未完成でも動く）
#
# parser.py・database.py が揃えば上の /analyze/{match_id} を使う。
# 間に合わなかった場合はこちらのルートで発表する。
# ローカルの CSV を直接読み込んで engine.py を呼ぶだけなので
# Supabase・CSV アップロード・2年生の実装に一切依存しない。
# ================================================================== #

_DATADIR = os.path.join(_BACKEND_DIR, "data")
_local_cache: dict = {}  # ゲームデータのメモリキャッシュ


def _load_local(game_id: int):
    """ローカル CSV からデータを読み込んでキャッシュする"""
    if game_id in _local_cache:
        return _local_cache[game_id]

    home   = mio.tracking_data(_DATADIR, game_id, 'Home')
    away   = mio.tracking_data(_DATADIR, game_id, 'Away')
    events = mio.read_event_data(_DATADIR, game_id)
    home   = mio.to_metric_coordinates(home)
    away   = mio.to_metric_coordinates(away)
    events = mio.to_metric_coordinates(events)
    home, away, events = mio.to_single_playing_direction(home, away, events)
    home   = mvel.calc_player_velocities(home, smoothing=True)
    away   = mvel.calc_player_velocities(away, smoothing=True)
    gk     = (mio.find_goalkeeper(home), mio.find_goalkeeper(away))

    _local_cache[game_id] = (home, away, events, gk)
    return _local_cache[game_id]


@app.get("/local/{game_id}/top_events")
def local_top_events(game_id: int, n: int = 10):
    """
    【発表用フォールバック】
    ローカルの player_importance.csv から上位 N 件を返す。
    parser.py / database.py の実装を必要としない。
    """
    csv_path = os.path.join(_DATADIR, f"Sample_Game_{game_id}", "player_importance.csv")
    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail="player_importance.csv が見つかりません。")

    try:
        home, away, events, gk = _load_local(game_id)
        df  = pd.read_csv(csv_path)
        top = (df.sort_values('importance_score', ascending=False)
                 .drop_duplicates(['player_id', 'event_id'])
                 .head(n))

        result = []
        for _, row in top.iterrows():
            try:
                ev = events.loc[int(row['event_id'])]
                result.append({
                    'rank':             len(result) + 1,
                    'event_id':         int(row['event_id']),
                    'frame_id':         int(row['frame_id']),
                    'player_id':        row['player_id'],
                    'team':             row['team'],
                    'importance_score': round(float(row['importance_score']), 4),
                    'marginal_pc':      round(float(row['marginal_pc']), 4),
                    'event_type':       str(ev.get('Type', '')),
                })
            except Exception:
                continue
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/local/{game_id}/counterfactual")
def local_counterfactual(game_id: int, event_id: int, player_id: str):
    """
    【発表用フォールバック】
    ローカルデータを使って反事実PCヒートマップを計算して返す。
    parser.py / database.py の実装を必要としない。
    """
    try:
        home, away, events, gk = _load_local(game_id)
        return calculate_counterfactual(home, away, events, event_id, player_id, gk)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"event_id={event_id} が見つかりません。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

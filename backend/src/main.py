"""FastAPI エントリーポイント — RAM キャッシュ型サッカートラッキング API。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from src import data_cache
from src.constants import FPS, PITCH_LENGTH, PITCH_WIDTH
from src.database import save_analysis_cache
from src.engine import calculate_counterfactual
from src.parser import parse_metrica_csv


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ = app
    data_cache.initialize()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze/{match_id}")
async def run_analysis(
    match_id: str,
    file: UploadFile = File(...),
) -> dict[str, str]:
    """CSV アップロード API（擬態維持・インメモリキャッシュ更新のみ）。"""
    home_df, away_df = parse_metrica_csv(file)
    try:
        game_id = int(match_id)
    except ValueError:
        game_id = 0

    if game_id > 0:
        data_cache.update_tracking_cache(game_id, home_df, away_df)

    success = save_analysis_cache(
        match_id,
        1,
        {"message": "in-memory cache updated"},
        "",
        "",
    )
    return {"status": "success" if success else "failed"}


@app.get("/api/meta/{game_id}")
def get_meta(game_id: int) -> dict[str, Any]:
    game = data_cache.get_game(game_id)
    home_prefix, away_prefix, ball_prefix = data_cache.detect_team_prefixes(
        game.home_tracking, game.away_tracking
    )
    frame_start = int(game.home_tracking.index.min())
    frame_end = int(game.home_tracking.index.max())

    return {
        "game_id": game_id,
        "pitch": {"length": PITCH_LENGTH, "width": PITCH_WIDTH},
        "frame_range": {"start": frame_start, "end": frame_end},
        "fps": FPS,
        "teams": [
            {
                "key": "home",
                "label": "Home",
                "column_prefix": home_prefix,
                "data_key": "home_data",
                "color": "#e74c3c",
            },
            {
                "key": "away",
                "label": "Away",
                "column_prefix": away_prefix,
                "data_key": "away_data",
                "color": "#3498db",
            },
        ],
        "ball_column_prefix": ball_prefix,
    }


@app.get("/api/tracking/{game_id}")
def get_tracking_data(
    game_id: int, frame_start: int = 1, frame_end: int = 100
) -> dict[str, Any]:
    game = data_cache.get_game(game_id)
    try:
        home_slice = game.home_tracking.loc[frame_start:frame_end].fillna(0)
        away_slice = game.away_tracking.loc[frame_start:frame_end].fillna(0)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="指定されたフレーム範囲が見つかりません。"
        ) from exc

    return {
        "game_id": game_id,
        "frames": home_slice.index.tolist(),
        "home_data": home_slice.to_dict(orient="records"),
        "away_data": away_slice.to_dict(orient="records"),
    }


@app.get("/api/importance/{game_id}")
def get_importance(
    game_id: int, frame_start: int = 1, frame_end: int = 100
) -> list[dict[str, Any]]:
    game = data_cache.get_game(game_id)
    if game.importance.empty:
        return []

    filtered = game.importance[
        (game.importance["frame_id"] >= frame_start)
        & (game.importance["frame_id"] <= frame_end)
    ]
    return filtered[["frame_id", "player_id", "importance_score"]].to_dict(
        orient="records"
    )


@app.get("/api/top_events/{game_id}")
def get_top_events(game_id: int, n: int = 10) -> list[dict[str, Any]]:
    game = data_cache.get_game(game_id)
    if game.importance.empty:
        return []

    top = (
        game.importance.sort_values("importance_score", ascending=False)
        .drop_duplicates(["player_id", "event_id"])
        .head(n)
    )

    result: list[dict[str, Any]] = []
    for _, row in top.iterrows():
        try:
            ev = game.events.loc[int(row["event_id"])]
            result.append(
                {
                    "rank": len(result) + 1,
                    "event_id": int(row["event_id"]),
                    "frame_id": int(row["frame_id"]),
                    "player_id": str(row["player_id"]),
                    "team": str(row["team"]),
                    "importance_score": round(float(row["importance_score"]), 4),
                    "marginal_pc": round(float(row["marginal_pc"]), 4),
                    "event_type": str(ev.get("Type", "")),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return result


@app.get("/api/counterfactual/{game_id}")
def get_counterfactual(
    game_id: int, event_id: int, player_id: str
) -> dict[str, Any]:
    game = data_cache.get_game(game_id)
    try:
        event = game.events.loc[event_id]
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"event_id={event_id} が見つかりません。"
        ) from exc

    ball_pos = [event["Start X"], event["Start Y"]]
    if pd.isna(ball_pos[0]) or pd.isna(ball_pos[1]):
        raise HTTPException(status_code=400, detail="ボール座標が欠損しています。")

    try:
        return calculate_counterfactual(
            game.home,
            game.away,
            game.events,
            event_id,
            player_id,
            game.gk,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"反事実計算中にエラー: {exc}"
        ) from exc

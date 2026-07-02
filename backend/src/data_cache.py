"""起動時 RAM キャッシュ — ローカル CSV を前処理して常駐させる。"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

import pandas as pd

from src.constants import DEFAULT_GAME_ID
from src.scripts import Metrica_IO as mio
from src.scripts import Metrica_Velocities as mvel

logger = logging.getLogger(__name__)

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATADIR = os.path.join(_BACKEND_DIR, "data")

_game_cache: dict[int, GameData] = {}


@dataclass
class GameData:
    """tracking_* は /api/tracking 用、home/away は反事実計算用。"""

    home_tracking: pd.DataFrame
    away_tracking: pd.DataFrame
    home: pd.DataFrame
    away: pd.DataFrame
    events: pd.DataFrame
    gk: tuple[str, str]
    importance: pd.DataFrame
    is_mock: bool


def initialize() -> None:
    """サーバー起動時にデフォルト試合データをロードする。"""
    _game_cache.clear()
    preload_game(DEFAULT_GAME_ID)


def preload_game(game_id: int) -> GameData:
    """指定試合をキャッシュに載せる（既にあれば再利用）。"""
    if game_id in _game_cache:
        return _game_cache[game_id]

    importance = _load_importance(game_id)
    try:
        game = _load_from_disk(game_id, importance)
    except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
        logger.warning(
            "game_id=%s の CSV が見つからないか読込に失敗しました。モックデータにフォールバック: %s",
            game_id,
            exc,
        )
        game = _create_mock_game(game_id)
        game.importance = importance

    _game_cache[game_id] = game
    return game


def get_game(game_id: int) -> GameData:
    """キャッシュから試合データを取得する（未ロードならその場でロード）。"""
    return preload_game(game_id)


def update_tracking_cache(
    game_id: int, home_df: pd.DataFrame, away_df: pd.DataFrame
) -> None:
    """POST /analyze 用: インメモリキャッシュを更新する。"""
    if home_df.empty and away_df.empty:
        return

    home_metric = mio.to_metric_coordinates(home_df.copy())
    away_metric = mio.to_metric_coordinates(away_df.copy())
    home_tracking = mvel.calc_player_velocities(home_metric.copy(), smoothing=True)
    away_tracking = mvel.calc_player_velocities(away_metric.copy(), smoothing=True)

    events = _game_cache.get(game_id)
    events_df = events.events if events else _create_mock_events(game_id)
    home_cf, away_cf, events_cf = mio.to_single_playing_direction(
        home_tracking.copy(), away_tracking.copy(), events_df.copy()
    )
    gk = (mio.find_goalkeeper(home_cf), mio.find_goalkeeper(away_cf))
    importance = events.importance if events else _empty_importance()

    _game_cache[game_id] = GameData(
        home_tracking=home_tracking,
        away_tracking=away_tracking,
        home=home_cf,
        away=away_cf,
        events=events_cf,
        gk=gk,
        importance=importance,
        is_mock=False,
    )


def _load_importance(game_id: int) -> pd.DataFrame:
    importance_path = os.path.join(
        DATADIR, f"Sample_Game_{game_id}", "player_importance.csv"
    )
    if os.path.exists(importance_path):
        return pd.read_csv(importance_path)
    return _empty_importance()


def _load_from_disk(game_id: int, importance: pd.DataFrame) -> GameData:
    home_raw = mio.tracking_data(DATADIR, game_id, "Home")
    away_raw = mio.tracking_data(DATADIR, game_id, "Away")
    events_raw = mio.read_event_data(DATADIR, game_id)

    home_metric = mio.to_metric_coordinates(home_raw)
    away_metric = mio.to_metric_coordinates(away_raw)
    events_metric = mio.to_metric_coordinates(events_raw)

    home_tracking = mvel.calc_player_velocities(home_metric.copy(), smoothing=True)
    away_tracking = mvel.calc_player_velocities(away_metric.copy(), smoothing=True)

    home, away, events = mio.to_single_playing_direction(
        home_tracking.copy(), away_tracking.copy(), events_metric.copy()
    )
    gk = (mio.find_goalkeeper(home), mio.find_goalkeeper(away))

    return GameData(
        home_tracking=home_tracking,
        away_tracking=away_tracking,
        home=home,
        away=away,
        events=events,
        gk=gk,
        importance=importance,
        is_mock=False,
    )


def _empty_importance() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "frame_id",
            "player_id",
            "team",
            "marginal_pc",
            "importance_score",
        ]
    )


def _create_mock_events(game_id: int) -> pd.DataFrame:
    _ = game_id
    return pd.DataFrame(
        {
            "Team": ["Home"],
            "Type": ["PASS"],
            "Start Frame": [1],
            "Start X": [0.0],
            "Start Y": [0.0],
            "Period": [1],
        },
        index=[0],
    )


def _create_mock_game(game_id: int) -> GameData:
    """CI や CSV 不在時でもサーバーが起動できる最小モックデータ。"""
    _ = game_id
    frames = [1, 2, 3]
    home_tracking = pd.DataFrame(
        {
            "Period": [1, 1, 1],
            "Time [s]": [0.0, 0.04, 0.08],
            "Home_1_x": [10.0, 10.5, 11.0],
            "Home_1_y": [0.0, 0.0, 0.0],
            "Home_1_vx": [0.0, 12.5, 12.5],
            "Home_1_vy": [0.0, 0.0, 0.0],
            "ball_x": [0.0, 0.0, 0.0],
            "ball_y": [0.0, 0.0, 0.0],
        },
        index=frames,
    )
    away_tracking = pd.DataFrame(
        {
            "Period": [1, 1, 1],
            "Time [s]": [0.0, 0.04, 0.08],
            "Away_1_x": [-10.0, -10.0, -10.0],
            "Away_1_y": [0.0, 0.0, 0.0],
            "Away_1_vx": [0.0, 0.0, 0.0],
            "Away_1_vy": [0.0, 0.0, 0.0],
            "ball_x": [0.0, 0.0, 0.0],
            "ball_y": [0.0, 0.0, 0.0],
        },
        index=frames,
    )
    home_tracking.index.name = "Frame"
    away_tracking.index.name = "Frame"

    events = mio.to_metric_coordinates(_create_mock_events(game_id))

    return GameData(
        home_tracking=home_tracking,
        away_tracking=away_tracking,
        home=home_tracking.copy(),
        away=away_tracking.copy(),
        events=events,
        gk=("1", "1"),
        importance=_empty_importance(),
        is_mock=True,
    )


def detect_team_prefixes(
    tracking_home: pd.DataFrame, tracking_away: pd.DataFrame
) -> tuple[str, str, str]:
    """カラム名から Home/Away/ボールのプレフィックスを検出する。"""
    home_x_cols = [
        c
        for c in tracking_home.columns
        if c.endswith("_x") and not c.endswith("_vx") and "ball" not in c.lower()
    ]
    away_x_cols = [
        c
        for c in tracking_away.columns
        if c.endswith("_x") and not c.endswith("_vx") and "ball" not in c.lower()
    ]

    home_prefix = (
        re.sub(r"_\d+_x$", "", home_x_cols[0]) if home_x_cols else "Home"
    )
    away_prefix = (
        re.sub(r"_\d+_x$", "", away_x_cols[0]) if away_x_cols else "Away"
    )

    ball_x_cols = [
        c for c in tracking_home.columns if "ball" in c.lower() and c.endswith("_x")
    ]
    ball_prefix = ball_x_cols[0][:-2] if ball_x_cols else "ball"

    return home_prefix, away_prefix, ball_prefix

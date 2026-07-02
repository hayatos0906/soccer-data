"""
engine.py — ピッチコントロール計算コアエンジン（先輩担当聖域）

Spearman (2018) ピッチコントロールモデル + 反事実分析。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.constants import FIELD_DIMEN
from src.scripts import Metrica_IO as mio
from src.scripts import Metrica_PitchControl as mpc

N_GRID_X = 25
GAUSSIAN_SIGMA = 20.0
PASSIVE_DIST_THRESH = 40.0


def _active_players(players: list[mpc.player], ball_pos: np.ndarray) -> list[mpc.player]:
    """GK と局面外（40m超）の選手を除外する。"""
    return [
        p
        for p in players
        if not p.is_gk
        and np.linalg.norm(p.position - ball_pos) <= PASSIVE_DIST_THRESH
    ]


def _gaussian_weight(target: np.ndarray, ball_pos: np.ndarray) -> float:
    distance = np.linalg.norm(target - ball_pos)
    return float(np.exp(-(distance**2) / (2.0 * GAUSSIAN_SIGMA**2)))


def _compute_pc_grid(
    att: list[mpc.player],
    defn: list[mpc.player],
    ball_pos: np.ndarray,
    params: dict[str, float],
    n_x: int = N_GRID_X,
    field: tuple[float, float] = FIELD_DIMEN,
) -> tuple[np.ndarray, np.ndarray, list[float], list[float]]:
    n_y = int(n_x * field[1] / field[0])
    dx = field[0] / n_x
    dy = field[1] / n_y
    xgrid = np.arange(n_x) * dx - field[0] / 2.0 + dx / 2.0
    ygrid = np.arange(n_y) * dy - field[1] / 2.0 + dy / 2.0

    grid = np.zeros((n_y, n_x))
    weights = np.zeros((n_y, n_x))

    for i in range(n_y):
        for j in range(n_x):
            target = np.array([xgrid[j], ygrid[i]])
            weights[i, j] = _gaussian_weight(target, ball_pos)
            ppcfa, _ = mpc.calculate_pitch_control_at_target(
                target, att, defn, ball_pos, params
            )
            grid[i, j] = ppcfa

    return grid, weights, xgrid.tolist(), ygrid.tolist()


def calculate_pitch_control(
    home_df: pd.DataFrame,
    away_df: pd.DataFrame,
    frame_id: int,
    ball_pos: np.ndarray | None = None,
    gk_numbers: tuple[str, str] | None = None,
) -> dict[str, list[list[float]] | list[float]]:
    """指定フレームのガウス重み付きピッチコントロールグリッドを返す。"""
    if ball_pos is None:
        ball_pos = np.array([0.0, 0.0])

    if gk_numbers is None:
        gk_numbers = (mio.find_goalkeeper(home_df), mio.find_goalkeeper(away_df))

    params = mpc.default_model_params()
    att = mpc.initialise_players(home_df.loc[frame_id], "Home", params, gk_numbers[0])
    defn = mpc.initialise_players(away_df.loc[frame_id], "Away", params, gk_numbers[1])
    att = _active_players(att, ball_pos)
    defn = _active_players(defn, ball_pos)

    grid, weights, xgrid, ygrid = _compute_pc_grid(att, defn, ball_pos, params)

    return {
        "grid": grid.tolist(),
        "weights": weights.tolist(),
        "xgrid": xgrid,
        "ygrid": ygrid,
    }


def calculate_counterfactual(
    home_df: pd.DataFrame,
    away_df: pd.DataFrame,
    events_df: pd.DataFrame,
    event_id: int,
    player_id: str,
    gk_numbers: tuple[str, str] | None = None,
) -> dict[str, object]:
    """指定選手の反事実ピッチコントロール差分グリッドを返す。"""
    event = events_df.loc[event_id]
    frame_id = int(event["Start Frame"])
    possession_team = str(event["Team"])
    ball_pos = np.array([event["Start X"], event["Start Y"]])

    if gk_numbers is None:
        gk_numbers = (mio.find_goalkeeper(home_df), mio.find_goalkeeper(away_df))

    params = mpc.default_model_params()

    if possession_team == "Home":
        att = mpc.initialise_players(
            home_df.loc[frame_id], "Home", params, gk_numbers[0]
        )
        defn = mpc.initialise_players(
            away_df.loc[frame_id], "Away", params, gk_numbers[1]
        )
    else:
        defn = mpc.initialise_players(
            home_df.loc[frame_id], "Home", params, gk_numbers[0]
        )
        att = mpc.initialise_players(
            away_df.loc[frame_id], "Away", params, gk_numbers[1]
        )

    att = _active_players(att, ball_pos)
    defn = _active_players(defn, ball_pos)

    grid_base, weights, xgrid, ygrid = _compute_pc_grid(att, defn, ball_pos, params)

    target_prefix = player_id.split("_")[0]
    if target_prefix == possession_team:
        att_wo = [p for p in att if p.playername.rstrip("_") != player_id]
        grid_wo, _, _, _ = _compute_pc_grid(att_wo, defn, ball_pos, params)
        diff = grid_base - grid_wo
    else:
        def_wo = [p for p in defn if p.playername.rstrip("_") != player_id]
        grid_wo, _, _, _ = _compute_pc_grid(att, def_wo, ball_pos, params)
        diff = grid_wo - grid_base

    weighted_diff = diff * weights

    return {
        "event_id": event_id,
        "frame_id": frame_id,
        "player_id": player_id,
        "possession_team": possession_team,
        "ball_pos": ball_pos.tolist(),
        "xgrid": xgrid,
        "ygrid": ygrid,
        "baseline_grid": grid_base.tolist(),
        "diff_grid": weighted_diff.tolist(),
        "home_data": home_df.loc[frame_id].fillna(0).to_dict(),
        "away_data": away_df.loc[frame_id].fillna(0).to_dict(),
    }

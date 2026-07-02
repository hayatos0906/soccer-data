"""
engine.py — ピッチコントロール計算コアエンジン（先輩担当聖域）

【数理モデル】
Spearman (2018) "Off the Ball Scoring Opportunities" のピッチコントロールモデルに
反事実分析（Counterfactual Analysis）を組み合わせて選手の真のオフボール貢献度を測る。

【ガウス重み付け】
全グリッドを均等に評価するとボール遠方の後方スペースを管理するDFが過大評価されるため、
各セルにボールからの距離に応じたガウス重み w = exp(-d²/2σ²) を掛けて加重平均をとる。
σ=20m: 35m離れたセルは約10%にまで減衰 → MF/FWのボール近傍貢献を正当に評価できる。
"""

import os
import sys

import numpy as np
import pandas as pd

# backend/scripts を参照できるようにパスを追加
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from scripts import Metrica_PitchControl as mpc

# ------------------------------------------------------------------ #
# 定数
# ------------------------------------------------------------------ #
N_GRID_X              = 25    # 可視化用グリッド解像度（分析用は50）
GAUSSIAN_SIGMA        = 20.0  # ガウス重みの標準偏差 [m]
PASSIVE_DIST_THRESH   = 40.0  # この距離を超えた選手は「局面外」とみなして除外 [m]


# ------------------------------------------------------------------ #
# 内部ユーティリティ
# ------------------------------------------------------------------ #

def _active_players(players: list, ball_pos: np.ndarray) -> list:
    """
    GK とボールから PASSIVE_DIST_THRESH メートル超の選手を除外する。

    除外対象:
      - GK: ゴール前を守るだけで局面への能動的寄与が間接的
      - 40m 超: 攻撃側後方残留DF・守備側カウンター待機FWが典型
        （「誰でも代替できる立ち位置」のため分析対象外）
    DFのカバーリングは通常 15〜30m 圏内なので除外されない。
    """
    return [
        p for p in players
        if not p.is_gk
        and np.linalg.norm(p.position - ball_pos) <= PASSIVE_DIST_THRESH
    ]


def _gaussian_weight(target: np.ndarray, ball_pos: np.ndarray) -> float:
    """ボールからの距離に応じたガウス重み（0〜1）"""
    d = np.linalg.norm(target - ball_pos)
    return float(np.exp(-d**2 / (2.0 * GAUSSIAN_SIGMA**2)))


def _compute_pc_grid(
    att: list,
    defn: list,
    ball_pos: np.ndarray,
    params: dict,
    n_x: int = N_GRID_X,
    field: tuple = (106.0, 68.0),
) -> tuple[np.ndarray, np.ndarray, list, list]:
    """
    ガウス重み付きピッチコントロールグリッドを計算する。

    Returns
    -------
    grid         : (n_y, n_x) 各セルの攻撃チーム PC 値
    weights      : (n_y, n_x) 各セルのガウス重み
    xgrid, ygrid : セル中心座標リスト
    """
    n_y   = int(n_x * field[1] / field[0])
    dx    = field[0] / n_x
    dy    = field[1] / n_y
    xgrid = np.arange(n_x) * dx - field[0] / 2.0 + dx / 2.0
    ygrid = np.arange(n_y) * dy - field[1] / 2.0 + dy / 2.0

    grid    = np.zeros((n_y, n_x))
    weights = np.zeros((n_y, n_x))

    for i in range(n_y):
        for j in range(n_x):
            target       = np.array([xgrid[j], ygrid[i]])
            weights[i, j] = _gaussian_weight(target, ball_pos)
            ppcfa, _     = mpc.calculate_pitch_control_at_target(
                target, att, defn, ball_pos, params
            )
            grid[i, j] = ppcfa

    return grid, weights, xgrid.tolist(), ygrid.tolist()


# ------------------------------------------------------------------ #
# 公開インターフェース
# ------------------------------------------------------------------ #

def calculate_pitch_control(
    home_df: pd.DataFrame,
    away_df: pd.DataFrame,
    frame_id: int,
    ball_pos: np.ndarray | None = None,
    gk_numbers: tuple[str, str] | None = None,
) -> dict:
    """
    【先輩の担当聖域】
    指定フレームのガウス重み付きピッチコントロールグリッドを返す。

    Parameters
    ----------
    home_df     : to_metric_coordinates + calc_player_velocities 適用済みのDF
    away_df     : 同上
    frame_id    : 計算対象フレーム番号
    ball_pos    : ボール座標 [x, y]（メートル）。None の場合はゼロ位置
    gk_numbers  : (home_gk_id, away_gk_id)。None の場合は自動検出

    Returns
    -------
    {
      "grid"   : list[list[float]],  # (n_y, n_x) PC 値
      "weights": list[list[float]],  # ガウス重み
      "xgrid"  : list[float],
      "ygrid"  : list[float],
    }
    """
    if ball_pos is None:
        ball_pos = np.array([0.0, 0.0])

    if gk_numbers is None:
        from scripts import Metrica_IO as mio
        gk_numbers = (mio.find_goalkeeper(home_df), mio.find_goalkeeper(away_df))

    params = mpc.default_model_params()

    att  = mpc.initialise_players(home_df.loc[frame_id], 'Home', params, gk_numbers[0])
    defn = mpc.initialise_players(away_df.loc[frame_id], 'Away', params, gk_numbers[1])
    att  = _active_players(att,  ball_pos)
    defn = _active_players(defn, ball_pos)

    grid, weights, xgrid, ygrid = _compute_pc_grid(att, defn, ball_pos, params)

    return {
        "grid":    grid.tolist(),
        "weights": weights.tolist(),
        "xgrid":   xgrid,
        "ygrid":   ygrid,
    }


def calculate_counterfactual(
    home_df: pd.DataFrame,
    away_df: pd.DataFrame,
    events_df: pd.DataFrame,
    event_id: int,
    player_id: str,
    gk_numbers: tuple[str, str] | None = None,
) -> dict:
    """
    指定選手がいる場合/いない場合のPC差分（ガウス重み付き）を返す。

    diff_grid の読み方:
      正の値 = この選手がいることで生み出された（または守られた）空間
      大きいほど、その場所でのこの選手の貢献が大きい

    Returns
    -------
    {
      "diff_grid"     : list[list[float]],  # ガウス重み付き差分
      "baseline_grid" : list[list[float]],  # ベースラインPC
      "ball_pos"      : [float, float],
      "xgrid", "ygrid", "home_data", "away_data"
    }
    """
    event           = events_df.loc[event_id]
    frame_id        = int(event['Start Frame'])
    possession_team = event['Team']
    ball_pos        = np.array([event['Start X'], event['Start Y']])

    if gk_numbers is None:
        from scripts import Metrica_IO as mio
        gk_numbers = (mio.find_goalkeeper(home_df), mio.find_goalkeeper(away_df))

    params = mpc.default_model_params()

    if possession_team == 'Home':
        att  = mpc.initialise_players(home_df.loc[frame_id], 'Home', params, gk_numbers[0])
        defn = mpc.initialise_players(away_df.loc[frame_id], 'Away', params, gk_numbers[1])
    else:
        defn = mpc.initialise_players(home_df.loc[frame_id], 'Home', params, gk_numbers[0])
        att  = mpc.initialise_players(away_df.loc[frame_id], 'Away', params, gk_numbers[1])

    att  = _active_players(att,  ball_pos)
    defn = _active_players(defn, ball_pos)

    grid_base, weights, xgrid, ygrid = _compute_pc_grid(att, defn, ball_pos, params)

    target_prefix = player_id.split('_')[0]
    if target_prefix == possession_team:
        att_wo        = [p for p in att  if p.playername.rstrip('_') != player_id]
        grid_wo, _, _, _ = _compute_pc_grid(att_wo, defn, ball_pos, params)
        diff = grid_base - grid_wo
    else:
        def_wo        = [p for p in defn if p.playername.rstrip('_') != player_id]
        grid_wo, _, _, _ = _compute_pc_grid(att, def_wo, ball_pos, params)
        diff = grid_wo - grid_base

    weighted_diff = diff * weights

    return {
        "event_id":        event_id,
        "frame_id":        frame_id,
        "player_id":       player_id,
        "possession_team": possession_team,
        "ball_pos":        ball_pos.tolist(),
        "xgrid":           xgrid,
        "ygrid":           ygrid,
        "baseline_grid":   grid_base.tolist(),
        "diff_grid":       weighted_diff.tolist(),
        "home_data":       home_df.loc[frame_id].fillna(0).to_dict(),
        "away_data":       away_df.loc[frame_id].fillna(0).to_dict(),
    }

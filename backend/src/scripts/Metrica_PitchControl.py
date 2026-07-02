#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pitch Control モデル（LaurieOnTracking / Spearman 2018 由来）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.constants import FIELD_DIMEN


def initialise_players(
    team: pd.Series,
    teamname: str,
    params: dict[str, float],
    gkid: str,
) -> list[player]:
    """指定フレームの選手オブジェクトリストを生成する。"""
    player_ids = np.unique(
        [c.split("_")[1] for c in team.keys() if c[:4] == teamname]
    )
    team_players: list[player] = []
    for player_id in player_ids:
        team_player = player(str(player_id), team, teamname, params, gkid)
        if team_player.inframe:
            team_players.append(team_player)
    return team_players


def check_offsides(
    attacking_players: list[player],
    defending_players: list[player],
    ball_position: np.ndarray,
    gk_numbers: tuple[str, str],
    verbose: bool = False,
    tol: float = 0.2,
) -> list[player]:
    """オフサイドの攻撃選手を除外する。"""
    defending_gk_id = (
        gk_numbers[1] if attacking_players[0].teamname == "Home" else gk_numbers[0]
    )
    assert defending_gk_id in [p.id for p in defending_players]
    defending_gk = [p for p in defending_players if p.id == defending_gk_id][0]
    defending_half = np.sign(defending_gk.position[0])
    second_deepest_defender_x = sorted(
        [defending_half * p.position[0] for p in defending_players], reverse=True
    )[1]
    offside_line = (
        max(second_deepest_defender_x, defending_half * ball_position[0], 0.0) + tol
    )
    if verbose:
        for p in attacking_players:
            if p.position[0] * defending_half > offside_line:
                print(f"player {p.id} in {p.playername} team is offside")
    return [
        p
        for p in attacking_players
        if p.position[0] * defending_half <= offside_line
    ]


class player:
    """ピッチコントロール計算用の選手状態オブジェクト。"""

    id: str
    is_gk: bool
    teamname: str
    playername: str
    vmax: float
    reaction_time: float
    tti_sigma: float
    lambda_att: float
    lambda_def: float
    position: np.ndarray
    velocity: np.ndarray
    inframe: bool
    PPCF: float
    time_to_intercept: float

    def __init__(
        self,
        pid: str,
        team: pd.Series,
        teamname: str,
        params: dict[str, float],
        gkid: str,
    ) -> None:
        self.id = pid
        self.is_gk = self.id == gkid
        self.teamname = teamname
        self.playername = f"{teamname}_{pid}_"
        self.vmax = params["max_player_speed"]
        self.reaction_time = params["reaction_time"]
        self.tti_sigma = params["tti_sigma"]
        self.lambda_att = params["lambda_att"]
        self.lambda_def = (
            params["lambda_gk"] if self.is_gk else params["lambda_def"]
        )
        self.get_position(team)
        self.get_velocity(team)
        self.PPCF = 0.0

    def get_position(self, team: pd.Series) -> None:
        self.position = np.array(
            [team[self.playername + "x"], team[self.playername + "y"]]
        )
        self.inframe = not np.any(np.isnan(self.position))

    def get_velocity(self, team: pd.Series) -> None:
        self.velocity = np.array(
            [team[self.playername + "vx"], team[self.playername + "vy"]]
        )
        if np.any(np.isnan(self.velocity)):
            self.velocity = np.array([0.0, 0.0])

    def simple_time_to_intercept(self, r_final: np.ndarray) -> float:
        self.PPCF = 0.0
        r_reaction = self.position + self.velocity * self.reaction_time
        self.time_to_intercept = float(
            self.reaction_time
            + np.linalg.norm(r_final - r_reaction) / self.vmax
        )
        return float(self.time_to_intercept)

    def probability_intercept_ball(self, t: float) -> float:
        return float(
            1.0
            / (
                1.0
                + np.exp(
                    -np.pi
                    / np.sqrt(3.0)
                    / self.tti_sigma
                    * (t - self.time_to_intercept)
                )
            )
        )


def default_model_params(time_to_control_veto: int = 3) -> dict[str, float]:
    """Spearman (2018) モデルのデフォルトパラメータ。"""
    params: dict[str, float] = {}
    params["max_player_accel"] = 7.0
    params["max_player_speed"] = 5.0
    params["reaction_time"] = 0.7
    params["tti_sigma"] = 0.45
    params["kappa_def"] = 1.0
    params["lambda_att"] = 4.3
    params["lambda_def"] = 4.3 * params["kappa_def"]
    params["lambda_gk"] = params["lambda_def"] * 3.0
    params["average_ball_speed"] = 15.0
    params["int_dt"] = 0.04
    params["max_int_time"] = 10.0
    params["model_converge_tol"] = 0.01
    params["time_to_control_att"] = time_to_control_veto * np.log(10) * (
        np.sqrt(3) * params["tti_sigma"] / np.pi + 1 / params["lambda_att"]
    )
    params["time_to_control_def"] = time_to_control_veto * np.log(10) * (
        np.sqrt(3) * params["tti_sigma"] / np.pi + 1 / params["lambda_def"]
    )
    return params


def generate_pitch_control_for_event(
    event_id: int,
    events: pd.DataFrame,
    tracking_home: pd.DataFrame,
    tracking_away: pd.DataFrame,
    params: dict[str, float],
    gk_numbers: tuple[str, str],
    field_dimen: tuple[float, float] = FIELD_DIMEN,
    n_grid_cells_x: int = 50,
    offsides: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """イベント瞬間のピッチコントロールサーフェスを生成する。"""
    pass_frame = int(events.loc[event_id]["Start Frame"])
    pass_team = events.loc[event_id].Team
    ball_start_pos = np.array(
        [events.loc[event_id]["Start X"], events.loc[event_id]["Start Y"]]
    )
    n_grid_cells_y = int(n_grid_cells_x * field_dimen[1] / field_dimen[0])
    dx = field_dimen[0] / n_grid_cells_x
    dy = field_dimen[1] / n_grid_cells_y
    xgrid = np.arange(n_grid_cells_x) * dx - field_dimen[0] / 2.0 + dx / 2.0
    ygrid = np.arange(n_grid_cells_y) * dy - field_dimen[1] / 2.0 + dy / 2.0
    ppcfa = np.zeros(shape=(len(ygrid), len(xgrid)))
    ppcfd = np.zeros(shape=(len(ygrid), len(xgrid)))

    if pass_team == "Home":
        attacking_players = initialise_players(
            tracking_home.loc[pass_frame], "Home", params, gk_numbers[0]
        )
        defending_players = initialise_players(
            tracking_away.loc[pass_frame], "Away", params, gk_numbers[1]
        )
    elif pass_team == "Away":
        defending_players = initialise_players(
            tracking_home.loc[pass_frame], "Home", params, gk_numbers[0]
        )
        attacking_players = initialise_players(
            tracking_away.loc[pass_frame], "Away", params, gk_numbers[1]
        )
    else:
        raise AssertionError("Team in possession must be either home or away")

    if offsides:
        attacking_players = check_offsides(
            attacking_players, defending_players, ball_start_pos, gk_numbers
        )

    for i in range(len(ygrid)):
        for j in range(len(xgrid)):
            target_position = np.array([xgrid[j], ygrid[i]])
            ppcfa[i, j], ppcfd[i, j] = calculate_pitch_control_at_target(
                target_position,
                attacking_players,
                defending_players,
                ball_start_pos,
                params,
            )

    checksum = np.sum(ppcfa + ppcfd) / float(n_grid_cells_y * n_grid_cells_x)
    assert 1 - checksum < params["model_converge_tol"], f"Checksum failed: {checksum:.3f}"
    return ppcfa, xgrid, ygrid


def calculate_pitch_control_at_target(
    target_position: np.ndarray,
    attacking_players: list[player],
    defending_players: list[player],
    ball_start_pos: np.ndarray | None,
    params: dict[str, float],
) -> tuple[float, float]:
    """指定位置における攻撃・守備チームのピッチコントロール確率を返す。"""
    if ball_start_pos is None or any(np.isnan(ball_start_pos)):
        ball_travel_time = 0.0
    else:
        ball_travel_time = float(
            np.linalg.norm(target_position - ball_start_pos)
            / params["average_ball_speed"]
        )

    tau_min_att = np.nanmin(
        [p.simple_time_to_intercept(target_position) for p in attacking_players]
    )
    tau_min_def = np.nanmin(
        [p.simple_time_to_intercept(target_position) for p in defending_players]
    )

    if tau_min_att - max(ball_travel_time, tau_min_def) >= params["time_to_control_def"]:
        return 0.0, 1.0
    if tau_min_def - max(ball_travel_time, tau_min_att) >= params["time_to_control_att"]:
        return 1.0, 0.0

    attacking_players = [
        p
        for p in attacking_players
        if p.time_to_intercept - tau_min_att < params["time_to_control_att"]
    ]
    defending_players = [
        p
        for p in defending_players
        if p.time_to_intercept - tau_min_def < params["time_to_control_def"]
    ]

    dt_array = np.arange(
        ball_travel_time - params["int_dt"],
        ball_travel_time + params["max_int_time"],
        params["int_dt"],
    )
    ppcfatt = np.zeros_like(dt_array)
    ppcfdef = np.zeros_like(dt_array)
    ptot = 0.0
    i = 1
    while 1 - ptot > params["model_converge_tol"] and i < dt_array.size:
        t = dt_array[i]
        for pl in attacking_players:
            dppcfdt = (
                (1 - ppcfatt[i - 1] - ppcfdef[i - 1])
                * pl.probability_intercept_ball(t)
                * pl.lambda_att
            )
            assert dppcfdt >= 0, "Invalid attacking player probability"
            pl.PPCF += dppcfdt * params["int_dt"]
            ppcfatt[i] += pl.PPCF
        for pl in defending_players:
            dppcfdt = (
                (1 - ppcfatt[i - 1] - ppcfdef[i - 1])
                * pl.probability_intercept_ball(t)
                * pl.lambda_def
            )
            assert dppcfdt >= 0, "Invalid defending player probability"
            pl.PPCF += dppcfdt * params["int_dt"]
            ppcfdef[i] += pl.PPCF
        ptot = ppcfdef[i] + ppcfatt[i]
        i += 1

    if i >= dt_array.size:
        print(f"Integration failed to converge: {ptot:.3f}")

    return float(ppcfatt[i - 1]), float(ppcfdef[i - 1])

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Metrica トラッキングデータから選手速度を算出（LaurieOnTracking 由来）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.signal as signal


def calc_player_velocities(
    team: pd.DataFrame,
    smoothing: bool = True,
    filter_: str = "Savitzky-Golay",
    window: int = 7,
    polyorder: int = 1,
    maxspeed: float = 12,
) -> pd.DataFrame:
    """各フレームの速度ベクトル (_vx, _vy) と合計速度 (_speed) を追加する。"""
    team = remove_player_velocities(team)
    team = team.copy()

    player_ids = np.unique(
        [c[:-2] for c in team.columns if c[:4] in ["Home", "Away"]]
    )

    dt = team["Time [s]"].diff()
    second_half_idx = team.Period.idxmax()

    for player in player_ids:
        vx = team[f"{player}_x"].diff() / dt
        vy = team[f"{player}_y"].diff() / dt

        if maxspeed > 0:
            raw_speed = np.sqrt(vx**2 + vy**2)
            vx[raw_speed > maxspeed] = np.nan
            vy[raw_speed > maxspeed] = np.nan

        if smoothing:
            if filter_ == "Savitzky-Golay":
                vx.loc[:second_half_idx] = signal.savgol_filter(
                    vx.loc[:second_half_idx],
                    window_length=window,
                    polyorder=polyorder,
                )
                vy.loc[:second_half_idx] = signal.savgol_filter(
                    vy.loc[:second_half_idx],
                    window_length=window,
                    polyorder=polyorder,
                )
                vx.loc[second_half_idx:] = signal.savgol_filter(
                    vx.loc[second_half_idx:],
                    window_length=window,
                    polyorder=polyorder,
                )
                vy.loc[second_half_idx:] = signal.savgol_filter(
                    vy.loc[second_half_idx:],
                    window_length=window,
                    polyorder=polyorder,
                )
            elif filter_ == "moving average":
                ma_window = np.ones(window) / window
                vx.loc[:second_half_idx] = np.convolve(
                    vx.loc[:second_half_idx], ma_window, mode="same"
                )
                vy.loc[:second_half_idx] = np.convolve(
                    vy.loc[:second_half_idx], ma_window, mode="same"
                )
                vx.loc[second_half_idx:] = np.convolve(
                    vx.loc[second_half_idx:], ma_window, mode="same"
                )
                vy.loc[second_half_idx:] = np.convolve(
                    vy.loc[second_half_idx:], ma_window, mode="same"
                )

        team[f"{player}_vx"] = vx
        team[f"{player}_vy"] = vy
        team[f"{player}_speed"] = np.sqrt(vx**2 + vy**2)

    return team


def remove_player_velocities(team: pd.DataFrame) -> pd.DataFrame:
    """既存の速度・加速度列を除去する。"""
    columns = [
        c
        for c in team.columns
        if c.split("_")[-1]
        in ["vx", "vy", "ax", "ay", "speed", "acceleration"]
    ]
    return team.drop(columns=columns)

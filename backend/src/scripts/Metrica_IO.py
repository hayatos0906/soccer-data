#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Metrica サンプルデータ読み込み（LaurieOnTracking 由来）。"""

from __future__ import annotations

import csv

import numpy as np
import pandas as pd

from src.constants import FIELD_DIMEN


def read_match_data(
    datadir: str, gameid: int
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """ホーム・アウェイ・イベントデータをまとめて読み込む。"""
    tracking_home = tracking_data(datadir, gameid, "Home")
    tracking_away = tracking_data(datadir, gameid, "Away")
    events = read_event_data(datadir, gameid)
    return tracking_home, tracking_away, events


def read_event_data(datadir: str, game_id: int) -> pd.DataFrame:
    """Metrica イベント CSV を DataFrame で返す。"""
    eventfile = f"/Sample_Game_{game_id}/Sample_Game_{game_id}_RawEventsData.csv"
    return pd.read_csv(f"{datadir}{eventfile}")


def tracking_data(datadir: str, game_id: int, teamname: str) -> pd.DataFrame:
    """Metrica トラッキング CSV（_Team.csv 形式）を DataFrame で返す。"""
    teamfile = (
        f"/Sample_Game_{game_id}/Sample_Game_{game_id}_RawTrackingData_{teamname}_Team.csv"
    )
    filepath = f"{datadir}{teamfile}"

    with open(filepath, encoding="utf-8", newline="") as csvfile:
        reader = csv.reader(csvfile)
        next(reader)
        jerseys = [x for x in next(reader) if x != ""]
        columns = next(reader)
        for i, j in enumerate(jerseys):
            columns[i * 2 + 3] = f"{teamname}_{j}_x"
            columns[i * 2 + 4] = f"{teamname}_{j}_y"
        columns[-2] = "ball_x"
        columns[-1] = "ball_y"

    tracking = pd.read_csv(
        filepath, names=columns, index_col="Frame", skiprows=3
    )
    return tracking


def merge_tracking_data(home: pd.DataFrame, away: pd.DataFrame) -> pd.DataFrame:
    """ホーム・アウェイのトラッキングを単一 DataFrame にマージする。"""
    return home.drop(columns=["ball_x", "ball_y"]).merge(
        away, left_index=True, right_index=True
    )


def to_metric_coordinates(
    data: pd.DataFrame,
    field_dimen: tuple[float, float] = FIELD_DIMEN,
) -> pd.DataFrame:
    """Metrica 正規化座標 (0-1) をメートル（ピッチ中心原点）に変換する。"""
    x_columns = [c for c in data.columns if c[-1].lower() == "x"]
    y_columns = [c for c in data.columns if c[-1].lower() == "y"]
    data = data.copy()
    data[x_columns] = (data[x_columns] - 0.5) * field_dimen[0]
    data[y_columns] = -1 * (data[y_columns] - 0.5) * field_dimen[1]
    return data


def to_single_playing_direction(
    home: pd.DataFrame,
    away: pd.DataFrame,
    events: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """後半の座標を反転し、常に同一攻撃方向に統一する。"""
    home = home.copy()
    away = away.copy()
    events = events.copy()
    for team in (home, away, events):
        second_half_idx = team.Period[team.Period == 2].index[0]
        columns = [c for c in team.columns if c[-1].lower() in ["x", "y"]]
        team.loc[second_half_idx:, columns] *= -1
    return home, away, events


def find_playing_direction(team: pd.DataFrame, teamname: str) -> float:
    """キックオフ時 GK 位置から攻撃方向 (+1: 左→右) を推定する。"""
    gk_column_x = teamname + "_" + find_goalkeeper(team) + "_x"
    return float(-np.sign(team.iloc[0][gk_column_x]))


def find_goalkeeper(team: pd.DataFrame) -> str:
    """キックオフ時にゴールに最も近い選手を GK として返す。"""
    x_columns = [
        c
        for c in team.columns
        if c[-2:].lower() == "_x" and c[:4] in ["Home", "Away"]
    ]
    gk_col = team.iloc[0][x_columns].abs().idxmax()
    return str(gk_col.split("_")[1])

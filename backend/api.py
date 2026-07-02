from fastapi import APIRouter, HTTPException
import os
import re
import numpy as np
import pandas as pd

from backend.scripts import Metrica_IO as mio
from backend.scripts import Metrica_Velocities as mvel
from backend.scripts import Metrica_PitchControl as mpc

# ------------------------------------------------------------------ #
# データキャッシュ（初回ロードは数十秒かかるため、サーバー起動中は保持する）
# ------------------------------------------------------------------ #
_game_data_cache: dict = {}

def _load_game_data(game_id: int):
    """
    トラッキングデータを前処理済みの状態でキャッシュする。
    反事実計算エンドポイントが呼ばれるたびにロードし直すと数十秒かかるため、
    一度ロードしたらメモリに保持して使い回す。
    """
    if game_id in _game_data_cache:
        return _game_data_cache[game_id]

    home   = mio.tracking_data(DATADIR, game_id, 'Home')
    away   = mio.tracking_data(DATADIR, game_id, 'Away')
    events = mio.read_event_data(DATADIR, game_id)
    home   = mio.to_metric_coordinates(home)
    away   = mio.to_metric_coordinates(away)
    events = mio.to_metric_coordinates(events)
    home, away, events = mio.to_single_playing_direction(home, away, events)
    home   = mvel.calc_player_velocities(home, smoothing=True)
    away   = mvel.calc_player_velocities(away, smoothing=True)
    gk     = (mio.find_goalkeeper(home), mio.find_goalkeeper(away))
    params = mpc.default_model_params()

    _game_data_cache[game_id] = (home, away, events, gk, params)
    return _game_data_cache[game_id]


def _active_players(players, ball_pos, threshold=40.0):
    """GKとボールから40m超の選手を除外する（player_importance.py と同じ基準）"""
    return [
        p for p in players
        if not p.is_gk and np.linalg.norm(p.position - ball_pos) <= threshold
    ]


GAUSSIAN_SIGMA = 20.0  # player_importance.py と同じ値（ボール近傍を重視する標準偏差）

def _compute_pc_grid(att, defn, ball_pos, params, n_x=25, field=(106., 68.)):
    """
    指定した選手配置でピッチコントロールをグリッド全体で計算して返す。

    ガウス重みマップも同時に生成し、counterfactual 差分の可視化で
    「ボール近傍ほど色濃く」なるよう weighted_diff = diff × weights を返す。
    これにより、ボールから遠い後方スペースの差分は薄く表示され、
    中盤・ゴール前での貢献が視覚的に際立つ。
    """
    n_y   = int(n_x * field[1] / field[0])
    dx    = field[0] / n_x
    dy    = field[1] / n_y
    xgrid = np.arange(n_x) * dx - field[0] / 2. + dx / 2.
    ygrid = np.arange(n_y) * dy - field[1] / 2. + dy / 2.

    grid    = np.zeros((n_y, n_x))
    weights = np.zeros((n_y, n_x))

    for i in range(n_y):
        for j in range(n_x):
            target = np.array([xgrid[j], ygrid[i]])
            dist   = np.linalg.norm(target - ball_pos)
            weights[i, j] = np.exp(-dist**2 / (2.0 * GAUSSIAN_SIGMA**2))

            ppcfa, _ = mpc.calculate_pitch_control_at_target(
                target, att, defn, ball_pos, params
            )
            grid[i, j] = ppcfa

    return grid, weights, xgrid.tolist(), ygrid.tolist()

router = APIRouter()

# データディレクトリのパスを正しく設定
# このファイル(api.py)の1つ上の階層にある 'data' フォルダを指定
DATADIR = os.path.join(os.path.dirname(__file__), "data")

@router.get("/api/meta/{game_id}")
def get_meta(game_id: int):
    """
    データセットのメタ情報を返す。

    フロントエンドはここから「どんなカラム名か」「ピッチの大きさは何mか」を知り、
    Metrica 以外のデータセットに切り替えても app.js を変えずに動く設計にしている。
    """
    try:
        # 座標変換は不要 — カラム名とフレーム範囲だけが目的なのでそのまま読む
        tracking_home = mio.tracking_data(DATADIR, game_id, 'Home')
        tracking_away = mio.tracking_data(DATADIR, game_id, 'Away')

        frame_start = int(tracking_home.index.min())
        frame_end   = int(tracking_home.index.max())

        # チームプレフィックスをカラム名から検出する
        # 例: "Home_1_x" → split('_') = ["Home","1","x"] → prefix = "Home"
        # velocity カラム ("Home_1_vx") は '_vx' で終わるため除外してから検索
        home_x_cols = [c for c in tracking_home.columns
                       if c.endswith('_x') and not c.endswith('_vx') and 'ball' not in c.lower()]
        away_x_cols = [c for c in tracking_away.columns
                       if c.endswith('_x') and not c.endswith('_vx') and 'ball' not in c.lower()]

        # "Home_1_x" → "_1_x" を除いた先頭部分 = "Home"
        import re
        home_prefix = re.sub(r'_\d+_x$', '', home_x_cols[0]) if home_x_cols else 'Home'
        away_prefix = re.sub(r'_\d+_x$', '', away_x_cols[0]) if away_x_cols else 'Away'

        # ボールカラムのプレフィックスを検出 ("ball_x" → prefix = "ball")
        ball_x_cols = [c for c in tracking_home.columns
                       if 'ball' in c.lower() and c.endswith('_x')]
        ball_prefix = ball_x_cols[0][:-2] if ball_x_cols else 'ball'  # "_x" の2文字を除去

        return {
            "game_id": game_id,
            "pitch":   {"length": 106.0, "width": 68.0},
            "frame_range": {"start": frame_start, "end": frame_end},
            "fps": 25,
            "teams": [
                {
                    "key":            "home",
                    "label":          "Home",
                    "column_prefix":  home_prefix,
                    "data_key":       "home_data",
                    "color":          "#e74c3c",
                },
                {
                    "key":            "away",
                    "label":          "Away",
                    "column_prefix":  away_prefix,
                    "data_key":       "away_data",
                    "color":          "#3498db",
                },
            ],
            "ball_column_prefix": ball_prefix,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="指定された試合データが見つかりません。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"メタデータの取得中にエラー: {str(e)}")


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


@router.get("/api/events/{game_id}")
def get_events(game_id: int):
    """
    指定された試合のイベント一覧（パス・シュート等）を返すAPI。
    どのイベント(event_id)を指定してピッチコントロールを見るかを選ぶために使う。
    """
    try:
        events = mio.read_event_data(DATADIR, game_id)
        events_view = events[["Team", "Type", "Subtype", "Start Frame", "From", "To"]].reset_index()
        events_view = events_view.rename(columns={"index": "event_id"})
        return events_view.to_dict(orient="records")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="指定された試合データが見つかりません。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"データの処理中にエラーが発生しました: {str(e)}")


@router.get("/api/pitch_control/{game_id}")
def get_pitch_control(game_id: int, event_id: int):
    """
    指定されたイベントが起きた瞬間のピッチコントロール（支配領域）サーフェスを返すAPI。
    数値（パス成功数など）には現れない「スペースを作った/消した」効果を可視化するために使う。
    """
    try:
        tracking_home = mio.tracking_data(DATADIR, game_id, 'Home')
        tracking_away = mio.tracking_data(DATADIR, game_id, 'Away')
        events = mio.read_event_data(DATADIR, game_id)

        tracking_home = mio.to_metric_coordinates(tracking_home)
        tracking_away = mio.to_metric_coordinates(tracking_away)
        events = mio.to_metric_coordinates(events)
        tracking_home, tracking_away, events = mio.to_single_playing_direction(tracking_home, tracking_away, events)

        tracking_home = mvel.calc_player_velocities(tracking_home, smoothing=True)
        tracking_away = mvel.calc_player_velocities(tracking_away, smoothing=True)

        GK_numbers = (mio.find_goalkeeper(tracking_home), mio.find_goalkeeper(tracking_away))
        params = mpc.default_model_params()

        PPCFa, xgrid, ygrid = mpc.generate_pitch_control_for_event(
            event_id, events, tracking_home, tracking_away, params, GK_numbers
        )

        event = events.loc[event_id]
        return {
            "game_id": game_id,
            "event_id": event_id,
            "team_in_possession": event["Team"],
            "ball_start": [event["Start X"], event["Start Y"]],
            "xgrid": xgrid.tolist(),
            "ygrid": ygrid.tolist(),
            "pitch_control": PPCFa.tolist(),
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="指定された試合データが見つかりません。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"データの処理中にエラーが発生しました: {str(e)}")


@router.get("/api/importance/{game_id}")
def get_importance(game_id: int, frame_start: int = 1, frame_end: int = 100):
    """
    指定フレーム範囲の選手重要度スコアを返すAPI。
    player_importance.py で生成した CSV を読み込んで返す。
    フロントエンドでハイライト表示するために使う。
    """
    csv_path = os.path.join(DATADIR, f"Sample_Game_{game_id}", "player_importance.csv")
    if not os.path.exists(csv_path):
        raise HTTPException(
            status_code=404,
            detail="分析データが見つかりません。backend/scripts/player_importance.py を先に実行してください。"
        )
    try:
        df = pd.read_csv(csv_path)
        filtered = df[(df["frame_id"] >= frame_start) & (df["frame_id"] <= frame_end)]
        return filtered[["frame_id", "player_id", "importance_score"]].to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"データの処理中にエラーが発生しました: {str(e)}")


@router.get("/api/top_events/{game_id}")
def get_top_events(game_id: int, n: int = 10):
    """
    importance_score 上位 N 件の選手-イベントペアを返す。
    ハイライトパネルの一覧表示に使う。
    """
    csv_path = os.path.join(DATADIR, f"Sample_Game_{game_id}", "player_importance.csv")
    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail="分析データが見つかりません。")
    try:
        df = pd.read_csv(csv_path)
        top = (df.sort_values('importance_score', ascending=False)
                 .drop_duplicates(['player_id', 'event_id'])
                 .head(n))

        home, away, events, gk, params = _load_game_data(game_id)

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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/counterfactual/{game_id}")
def get_counterfactual(game_id: int, event_id: int, player_id: str):
    """
    指定選手がいる場合/いない場合のピッチコントロール差分グリッドを返す。

    diff_grid の読み方:
      攻撃選手 → 正の値 = この選手がいることで攻撃側が支配しているセル
      守備選手 → 正の値 = この選手がいることで守備側が抑えているセル
    いずれも「大きいほどこの選手の貢献が大きい場所」。
    """
    try:
        home, away, events, gk, params = _load_game_data(game_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"データロードエラー: {str(e)}")

    try:
        event = events.loc[event_id]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"event_id={event_id} が見つかりません。")

    frame_id        = int(event['Start Frame'])
    possession_team = event['Team']
    ball_pos        = np.array([event['Start X'], event['Start Y']])

    if np.any(np.isnan(ball_pos)):
        raise HTTPException(status_code=400, detail="ボール座標が欠損しています。")

    if possession_team == 'Home':
        att  = mpc.initialise_players(home.loc[frame_id], 'Home', params, gk[0])
        defn = mpc.initialise_players(away.loc[frame_id], 'Away', params, gk[1])
    else:
        defn = mpc.initialise_players(home.loc[frame_id], 'Home', params, gk[0])
        att  = mpc.initialise_players(away.loc[frame_id], 'Away', params, gk[1])

    att  = _active_players(att,  ball_pos)
    defn = _active_players(defn, ball_pos)

    grid_base, weights, xgrid, ygrid = _compute_pc_grid(att, defn, ball_pos, params)

    target_prefix = player_id.split('_')[0]
    if target_prefix == possession_team:
        att_wo = [p for p in att  if p.playername.rstrip('_') != player_id]
        grid_wo, _, _, _ = _compute_pc_grid(att_wo, defn, ball_pos, params)
        diff = grid_base - grid_wo
    else:
        def_wo = [p for p in defn if p.playername.rstrip('_') != player_id]
        grid_wo, _, _, _ = _compute_pc_grid(att, def_wo, ball_pos, params)
        diff = grid_wo - grid_base

    # ガウス重みを掛けた差分: ボール近傍の貢献を強調し、後方スペースの差分を抑制する
    weighted_diff = diff * weights

    home_frame = home.loc[frame_id].fillna(0).to_dict()
    away_frame = away.loc[frame_id].fillna(0).to_dict()

    return {
        'event_id':        event_id,
        'frame_id':        frame_id,
        'player_id':       player_id,
        'possession_team': possession_team,
        'ball_pos':        ball_pos.tolist(),
        'xgrid':           xgrid,
        'ygrid':           ygrid,
        'baseline_grid':   grid_base.tolist(),
        'diff_grid':       weighted_diff.tolist(),
        'home_data':       home_frame,
        'away_data':       away_frame,
    }
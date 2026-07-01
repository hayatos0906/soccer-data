from fastapi import APIRouter, HTTPException
import os
import pandas as pd

# 既存モジュールのインポート
# パス指定を避けるため、プロジェクトルートが適切に設定されている前提です
from backend.scripts import Metrica_IO as mio
from backend.scripts import Metrica_Velocities as mvel
from backend.scripts import Metrica_PitchControl as mpc

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
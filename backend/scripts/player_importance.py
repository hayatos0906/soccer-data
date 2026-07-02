"""
player_importance.py  ―  反事実ピッチコントロールによる選手オフボール貢献度

【このスクリプトが測るもの】
「もしこの選手がいなかったら、チームのピッチコントロールはどう変わっていたか」
= 反事実分析（Counterfactual Analysis）によるオフボール貢献度

【計算の仕組み】
各イベントに対して：
  1. アクティブ選手を選定（ボール付近 40m 以内 かつ GK 除外）
  2. アクティブ選手全員でピッチコントロールを計算（ベースライン）
  3. 選手Aを除いて再計算
  4. 差分 = 選手Aのいない世界との比較 = 選手Aの真の貢献度

【アクティブ選手の定義】
以下を「局面に関与していない」として除外する:
  - GK（ゴールキーパー）
  - ボールから 40m 超の選手:
      → 攻撃側の後方残留DF（カウンター対策で立っているだけ）
      → 守備側のカウンター待機FW（スペースが広いだけで能動的寄与なし）
  ※ DFのカバーリングは通常 15〜30m 圏内なので除外されない。

これにより：
  - 囮の動きでDFを引きつけた選手 → 高スコア
  - 立っているだけで誰でも代替できる選手 → スコアなし（分析対象外）
  - たまたま速く走っただけの選手 → 低スコア

【並列処理】
8コアを使って全イベントを並列計算。

【出力】
backend/data/Sample_Game_{id}/player_importance.csv

  列:
    event_id            : イベント番号
    frame_id            : フレーム番号
    player_id           : 例 "Home_1", "Away_15"
    team                : "Home" または "Away"
    marginal_pc         : 反事実ピッチコントロール貢献度（0〜1）
                          = 「この選手がいない世界との差」
    importance_score    : 全データ内で正規化したスコア（0〜1）

【使い方】
  python -m backend.scripts.player_importance --game_id 2
"""

import argparse
import os
import sys
import time
from multiprocessing import Pool, cpu_count

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.scripts import Metrica_IO as mio
from backend.scripts import Metrica_Velocities as mvel
from backend.scripts import Metrica_PitchControl as mpc

DATADIR = os.path.join(os.path.dirname(__file__), "..", "data")
N_GRID_CELLS_X = 50  # 標準解像度（妥協なし）

# ボールからこの距離（メートル）を超えた選手は局面への関与が低いとみなして除外する。
PASSIVE_DISTANCE_THRESHOLD = 30.0

# ガウス重みの標準偏差（メートル）。
# ボール付近のセルほど重く、遠いセルほど軽く評価することで、
# 「ボールから遠い後方スペースを管理するだけのDF」のスコアを自然に抑制し、
# ボール近傍で動くMF・FWのスペース創出を正当に評価する。
#   距離  0m → 重み 1.000  （ボール直近）
#   距離 10m → 重み 0.607
#   距離 20m → 重み 0.135  （σ=10m に変更）
#   距離 30m → 重み 0.011  （ほぼ無視）
GAUSSIAN_SIGMA = 10.0

# 速度フィルター閾値 [m/s]。
# これ未満の選手は「立っているだけ」とみなして除外する。
# 1.5 m/s = 小走り程度。止まっているDFや広がって静止しているFWが除外対象。
MIN_VELOCITY = 1.5

# 攻撃チームの選手がボールよりこの距離以上後方にいたら除外 [m]。
# 逆サイドFWがボールより前方に位置しても除外されないが、
# 後方で待機するDFはここで弾かれる。5m は「一歩下がった程度」を許容する余白。
BEHIND_BALL_MARGIN = 5.0

# ワーカープロセスが共有するデータ（各プロセスに一度だけロード）
_home            = None
_away            = None
_GK_numbers      = None
_params          = None
_home_att_dir    = None  # Homeチームの攻撃方向（+1 or -1）


def _filter_active_players(players, ball_pos, att_team, att_direction):
    """
    「局面に能動的に関与している」選手のみを返す。

    除外対象:
      1. GK
      2. ボールから PASSIVE_DISTANCE_THRESHOLD メートル超
      3. 速度が MIN_VELOCITY 未満（止まっているだけの選手）
      4. 攻撃チームの選手で、ボールより BEHIND_BALL_MARGIN メートル以上後方
           → 攻撃側の後方残留DFを除外。守備側には適用しない（守備ブロックは後方が正常）
    """
    active = []
    for p in players:
        if p.is_gk:
            continue
        if np.linalg.norm(p.position - ball_pos) > PASSIVE_DISTANCE_THRESHOLD:
            continue
        if np.linalg.norm(p.velocity) < MIN_VELOCITY:
            continue
        # 攻撃チームの選手が5m以上後方にいたら除外
        if p.teamname == att_team:
            behind = (p.position[0] - ball_pos[0]) * att_direction
            if behind < -BEHIND_BALL_MARGIN:
                continue
        active.append(p)
    return active


def _find_goalkeeper(team_df, teamname):
    """pandas バージョン差異を回避した GK 特定"""
    x_cols = [c for c in team_df.columns if c[-2:] == '_x' and c[:4] == teamname]
    return team_df.iloc[0][x_cols].abs().idxmax().split('_')[1]


def _init_worker(game_id, datadir):
    """
    各ワーカープロセスの初期化。
    データは一度だけロードしてグローバル変数に保持する。
    """
    global _home, _away, _GK_numbers, _params, _home_att_dir

    home   = mio.tracking_data(datadir, game_id, 'Home')
    away   = mio.tracking_data(datadir, game_id, 'Away')
    events = mio.read_event_data(datadir, game_id)

    home   = mio.to_metric_coordinates(home)
    away   = mio.to_metric_coordinates(away)
    events = mio.to_metric_coordinates(events)
    home, away, events = mio.to_single_playing_direction(home, away, events)

    home = mvel.calc_player_velocities(home, smoothing=True)
    away = mvel.calc_player_velocities(away, smoothing=True)

    _home         = home
    _away         = away
    _GK_numbers   = (_find_goalkeeper(home, 'Home'), _find_goalkeeper(away, 'Away'))
    _params       = mpc.default_model_params()
    _home_att_dir = int(mio.find_playing_direction(home, 'Home'))


def _calc_pc_surface(att_players, def_players, ball_pos, field_dimen=(106., 68.)):
    """
    ピッチコントロール面をガウス重み付きで計算し、攻撃チームの加重平均 PPCF を返す。

    【重み付けの意図】
    全セルを均等に扱うと、ボールから遠い後方スペースを管理するDFが
    過大評価されやすい。そこで各セルにボールからの距離に応じたガウス重みを掛け、
    ボール近傍の空間支配を重視する加重平均をとる。
      w(x,y) = exp( -‖(x,y) − ball‖² / (2 · σ²) )   σ = GAUSSIAN_SIGMA

    Returns
    -------
    PPCFa_weighted : float  ガウス重み付き加重平均ピッチコントロール
    player_ppcf    : dict   { player_name: 加重平均PPCF }
    """
    n_y = int(N_GRID_CELLS_X * field_dimen[1] / field_dimen[0])
    dx  = field_dimen[0] / N_GRID_CELLS_X
    dy  = field_dimen[1] / n_y
    xgrid = np.arange(N_GRID_CELLS_X) * dx - field_dimen[0] / 2. + dx / 2.
    ygrid = np.arange(n_y)            * dy - field_dimen[1] / 2. + dy / 2.

    all_players   = att_players + def_players
    player_ppcf   = {p.playername.rstrip('_'): 0.0 for p in all_players}
    PPCFa_total   = 0.0
    weight_total  = 0.0  # 正規化用（重みの合計）

    for i in range(len(ygrid)):
        for j in range(len(xgrid)):
            target = np.array([xgrid[j], ygrid[i]])

            # ボールからの距離に応じたガウス重み（遠いほど低い）
            dist = np.linalg.norm(target - ball_pos)
            w    = np.exp(-dist**2 / (2.0 * GAUSSIAN_SIGMA**2))

            ppcfa, _ = mpc.calculate_pitch_control_at_target(
                target, att_players, def_players, ball_pos, _params
            )
            PPCFa_total  += w * ppcfa
            weight_total += w
            for p in all_players:
                player_ppcf[p.playername.rstrip('_')] += w * p.PPCF

    return (
        PPCFa_total  / weight_total,
        {k: v / weight_total for k, v in player_ppcf.items()},
    )


def _process_event(args):
    """
    1イベントの反事実分析をワーカーが実行する関数。

    反事実分析の流れ:
      1. 全員でピッチコントロールを計算（ベースライン）
      2. 選手を1人ずつ除いて再計算
      3. ベースラインとの差 = その選手の限界貢献度（Marginal Contribution）

    ボール保持チームがアタッキング・相手がディフェンディングとして扱う。
    """
    event_id, event = args

    frame_id        = int(event['Start Frame'])
    possession_team = event['Team']
    ball_pos        = np.array([event['Start X'], event['Start Y']])

    if np.any(np.isnan(ball_pos)):
        return []
    if frame_id not in _home.index or frame_id not in _away.index:
        return []

    try:
        if possession_team == 'Home':
            att  = mpc.initialise_players(_home.loc[frame_id], 'Home', _params, _GK_numbers[0])
            defn = mpc.initialise_players(_away.loc[frame_id], 'Away', _params, _GK_numbers[1])
        else:
            defn = mpc.initialise_players(_home.loc[frame_id], 'Home', _params, _GK_numbers[0])
            att  = mpc.initialise_players(_away.loc[frame_id], 'Away', _params, _GK_numbers[1])

        # 攻撃方向（Home基準）から各チームの攻撃方向を決定
        att_direction = _home_att_dir if possession_team == 'Home' else -_home_att_dir

        # GK・後方残留DF・静止選手・逆サイド静止選手 を除外し、能動的に関与している選手だけを残す。
        att  = _filter_active_players(att,  ball_pos, possession_team, att_direction)
        defn = _filter_active_players(defn, ball_pos, possession_team, att_direction)

        # フィールドプレイヤーが一方でも 0 人なら PC が計算できないためスキップ
        if len(att) == 0 or len(defn) == 0:
            return []

        # --- ベースライン計算（アクティブ選手のみ）---
        baseline_pc, _ = _calc_pc_surface(att, defn, ball_pos)

        records = []

        # --- 攻撃選手を1人ずつ除いて反事実計算 ---
        for i, p in enumerate(att):
            att_without = [pl for pl in att if pl.id != p.id]
            pc_without, _ = _calc_pc_surface(att_without, defn, ball_pos)
            # 攻撃側: この選手がいない世界ではPCが下がる → 差が貢献度
            marginal = max(0.0, baseline_pc - pc_without)
            records.append({
                "event_id":   event_id,
                "frame_id":   frame_id,
                "player_id":  p.playername.rstrip('_'),
                "team":       p.teamname,
                "marginal_pc": round(float(marginal), 6),
            })

        # --- 守備選手を1人ずつ除いて反事実計算 ---
        for i, p in enumerate(defn):
            def_without = [pl for pl in defn if pl.id != p.id]
            pc_without, _ = _calc_pc_surface(att, def_without, ball_pos)
            # 守備側: この選手がいない世界では相手のPCが上がる → 差が守備貢献度
            marginal = max(0.0, pc_without - baseline_pc)
            records.append({
                "event_id":   event_id,
                "frame_id":   frame_id,
                "player_id":  p.playername.rstrip('_'),
                "team":       p.teamname,
                "marginal_pc": round(float(marginal), 6),
            })

        return records

    except Exception:
        return []


def run(game_id: int) -> str:
    n_cores = cpu_count()
    print(f"[設定] {n_cores} コア並列 / 全イベント反事実分析 / グリッド {N_GRID_CELLS_X}×{int(N_GRID_CELLS_X*68/106)}")

    # イベント一覧だけ先に読み込んでワーカーに配布するタスクを作る
    events_raw = mio.read_event_data(DATADIR, game_id)
    task_list  = list(events_raw.iterrows())
    print(f"[開始] 全 {len(task_list)} イベント → 推定所要時間: 約2〜3時間")

    start = time.time()

    with Pool(
        processes=n_cores,
        initializer=_init_worker,
        initargs=(game_id, DATADIR)
    ) as pool:
        results = []
        done    = 0
        for batch in pool.imap_unordered(_process_event, task_list, chunksize=5):
            results.extend(batch)
            done += 1
            if done % 100 == 0:
                elapsed   = time.time() - start
                remaining = elapsed / done * (len(task_list) - done)
                print(f"  進捗: {done}/{len(task_list)}  "
                      f"経過: {elapsed/60:.1f}分  残り推定: {remaining/60:.1f}分")

    print("[集計] スコアを正規化して CSV に出力中...")
    result = pd.DataFrame(results)

    if result.empty:
        print("⚠️  結果が空です。データを確認してください。")
        return ""

    max_pc = result['marginal_pc'].max()
    result['importance_score'] = (
        (result['marginal_pc'] / max_pc).round(4) if max_pc > 0 else 0.0
    )
    result = result.sort_values(['frame_id', 'team', 'player_id']).reset_index(drop=True)

    out_dir  = os.path.join(DATADIR, f"Sample_Game_{game_id}")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "player_importance.csv")
    result.to_csv(out_path, index=False, encoding="utf-8")

    total_min = (time.time() - start) / 60
    print(f"\n✅ 完了（所要時間: {total_min:.1f}分）")
    print(f"   イベント数: {result['event_id'].nunique()} / 行数: {len(result)}")
    print(f"\n【反事実ピッチコントロール貢献度 Top 10】")
    print(result.nlargest(10, 'importance_score')[
        ['frame_id', 'player_id', 'marginal_pc', 'importance_score']
    ].to_string(index=False))

    return out_path


if __name__ == "__main__":
    # macOS は Python 3.8 以降 spawn がデフォルトだが、
    # numpy/pandas を含む純 Python 計算には fork が安定して動く
    import multiprocessing
    multiprocessing.set_start_method('fork')

    parser = argparse.ArgumentParser()
    parser.add_argument("--game_id", type=int, default=2)
    args = parser.parse_args()
    run(args.game_id)

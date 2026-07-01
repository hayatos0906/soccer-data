/**
 * app.js — 汎用サッカートラッキング可視化
 *
 * ピッチ寸法・チーム名・カラム形式はすべて /api/meta から取得する。
 * データセットを変えても、バックエンドが正しいメタ情報を返せば
 * このファイルを修正する必要はない。
 */

const canvas = document.getElementById('pitchCanvas');
const ctx    = canvas.getContext('2d');

const HIGHLIGHT_HIGH   = 0.7;  // この値以上 → 黄色リング＋大きい円
const HIGHLIGHT_MEDIUM = 0.4;  // この値以上 → やや大きい円

// /api/meta から取得したデータセット情報をモジュールスコープで保持する
let meta = null;

// ------------------------------------------------------------------ //
// 描画ユーティリティ
// ------------------------------------------------------------------ //

/**
 * ピッチ背景とラインを描く。
 * scale（ピクセル/m）はメタデータ取得後に決まるため引数で受け取る。
 */
function drawPitch(scale) {
    ctx.fillStyle = '#4CAF50';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.strokeStyle = 'white';
    ctx.lineWidth = 2;

    // センターライン
    ctx.beginPath();
    ctx.moveTo(canvas.width / 2, 0);
    ctx.lineTo(canvas.width / 2, canvas.height);
    ctx.stroke();

    // センターサークル（半径 9.15m）
    ctx.beginPath();
    ctx.arc(canvas.width / 2, canvas.height / 2, 9.15 * scale, 0, Math.PI * 2);
    ctx.stroke();

    // タッチライン・ゴールライン（外枠）
    ctx.strokeRect(0, 0, canvas.width, canvas.height);
}

/**
 * ピッチ座標（メートル、中心原点）→ キャンバスピクセルに変換する。
 * halfLen = pitch.length / 2、halfWid = pitch.width / 2
 * ピッチ外の座標はキャンバス端に収める（clamp）。
 */
function toCanvas(x, y, scale, halfLen, halfWid) {
    const cx = Math.min(Math.max((x + halfLen) * scale, 0), canvas.width);
    const cy = Math.min(Math.max((y + halfWid) * scale, 0), canvas.height);
    return [cx, cy];
}

/**
 * 1人の選手を重要度スコアに応じてハイライト描画する。
 * score は 0〜1 の importance_score。
 */
function drawPlayer(cx, cy, color, score) {
    if (score >= HIGHLIGHT_HIGH) {
        // 高重要度: 黄色のリングを外側に重ねる
        ctx.beginPath();
        ctx.arc(cx, cy, 13, 0, Math.PI * 2);
        ctx.strokeStyle = 'yellow';
        ctx.lineWidth = 2.5;
        ctx.stroke();
    }

    const radius = 5 + score * 8;  // スコアに応じて 5〜13px
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();
}

// ------------------------------------------------------------------ //
// フレーム描画
// ------------------------------------------------------------------ //

/**
 * 1フレーム分の選手・ボールを描画する。
 *
 * チーム情報（カラムプレフィックス・色）は meta.teams から動的に取得するため、
 * Metrica 以外のデータセットでもそのまま動く。
 *
 * @param {Object} frameData     - { home_data: {...}, away_data: {...} }（1フレームのレコード）
 * @param {number} frameId       - 実フレーム番号（重要度マップの検索キー）
 * @param {Object} importanceMap - { frame_id: { player_id: score } }
 */
function drawFrame(frameData, frameId, importanceMap) {
    const scale   = canvas.width / meta.pitch.length;
    const halfLen = meta.pitch.length / 2;
    const halfWid = meta.pitch.width  / 2;

    drawPitch(scale);

    const frameScores = importanceMap[frameId] || {};

    for (const team of meta.teams) {
        const teamData = frameData[team.data_key];
        if (!teamData) continue;

        // カラム名からプレフィックスに一致するプレイヤーIDを動的に取得する。
        // 例: column_prefix="Home" のとき "Home_1_x" → id="1"
        // "_vx" で終わる速度カラムは明示的に除外する。
        const playerIds = Object.keys(teamData)
            .filter(k =>
                k.startsWith(team.column_prefix + '_') &&
                k.endsWith('_x') &&
                !k.endsWith('_vx')
            )
            .map(k => k.slice(team.column_prefix.length + 1, -2));
        // ↑ "Home_1_x".slice(5, -2) = "1"、"Away_15_x".slice(5, -2) = "15"

        for (const pid of playerIds) {
            const x = teamData[`${team.column_prefix}_${pid}_x`];
            const y = teamData[`${team.column_prefix}_${pid}_y`];
            if (x === 0 && y === 0) continue;  // フレーム外の選手（欠損を0で埋めた値）はスキップ

            const [cx, cy] = toCanvas(x, y, scale, halfLen, halfWid);
            const playerId = `${team.column_prefix}_${pid}`;
            const score    = frameScores[playerId] || 0;
            drawPlayer(cx, cy, team.color, score);
        }
    }

    // ボール（白）— ball_column_prefix から座標カラム名を決定する
    // 例: ball_column_prefix="ball" → "ball_x", "ball_y"
    const ballData = frameData[meta.teams[0].data_key];
    if (ballData) {
        const bx = ballData[`${meta.ball_column_prefix}_x`];
        const by = ballData[`${meta.ball_column_prefix}_y`];
        if (!(bx === 0 && by === 0)) {
            const [bcx, bcy] = toCanvas(bx, by, scale, halfLen, halfWid);
            ctx.fillStyle = 'white';
            ctx.beginPath();
            ctx.arc(bcx, bcy, 4, 0, Math.PI * 2);
            ctx.fill();
        }
    }
}

// ------------------------------------------------------------------ //
// データ変換
// ------------------------------------------------------------------ //

/**
 * 重要度データのリストを { frame_id: { player_id: score } } の辞書に変換する。
 * drawFrame 内で O(1) 参照するための前処理。
 */
function buildImportanceMap(importanceData) {
    const map = {};
    for (const row of importanceData) {
        if (!map[row.frame_id]) map[row.frame_id] = {};
        map[row.frame_id][row.player_id] = row.importance_score;
    }
    return map;
}

// ------------------------------------------------------------------ //
// メインフロー
// ------------------------------------------------------------------ //

const BASE_URL = 'http://127.0.0.1:8000';

/**
 * 描画ボタンが押されたときに実行されるメインフロー。
 *
 * 1. /api/meta でデータセット情報を取得し、canvas の高さを調整する
 * 2. トラッキングデータと重要度データを並列取得する
 * 3. フレームを順番に描画してアニメーションさせる
 */
async function fetchAndAnimate() {
    const gameId     = document.getElementById('gameIdInput').value;
    const frameStart = document.getElementById('frameStartInput').value;
    const frameEnd   = document.getElementById('frameEndInput').value;

    try {
        // メタデータを取得してから canvas を正しいアスペクト比に調整する
        const metaRes = await fetch(`${BASE_URL}/api/meta/${gameId}`);
        if (!metaRes.ok) throw new Error(`メタデータAPI エラー: ${metaRes.status}`);
        meta = await metaRes.json();

        // キャンバス幅は固定（HTML で設定）、高さだけピッチ比率から算出する
        const scale = canvas.width / meta.pitch.length;
        canvas.height = Math.round(meta.pitch.width * scale);

        // トラッキングデータと重要度データを並列取得する
        const [trackingRes, importanceRes] = await Promise.all([
            fetch(`${BASE_URL}/api/tracking/${gameId}?frame_start=${frameStart}&frame_end=${frameEnd}`),
            fetch(`${BASE_URL}/api/importance/${gameId}?frame_start=${frameStart}&frame_end=${frameEnd}`),
        ]);

        if (!trackingRes.ok) throw new Error(`トラッキングAPI エラー: ${trackingRes.status}`);
        const data = await trackingRes.json();

        // 重要度データは任意（CSVがなくてもアニメーションは動く）
        let importanceMap = {};
        if (importanceRes.ok) {
            importanceMap = buildImportanceMap(await importanceRes.json());
        }

        // フレームを順番に描画（meta.fps からフレーム間隔を決定）
        let frame = 0;
        function animate() {
            if (frame < data.home_data.length) {
                const frameId = data.frames[frame];
                drawFrame(
                    { home_data: data.home_data[frame], away_data: data.away_data[frame] },
                    frameId,
                    importanceMap
                );
                frame++;
                setTimeout(animate, 1000 / meta.fps);
            }
        }
        animate();

    } catch (err) {
        console.error('データ取得失敗:', err);
        alert('バックエンドに接続できませんでした。\nサーバーが起動しているか確認してください。');
    }
}

/**
 * ページ読み込み時に /api/meta を叩き、フレーム範囲の初期値をUIに設定する。
 * サーバーが起動していない場合は静かに失敗する。
 */
async function initUI() {
    const gameId = document.getElementById('gameIdInput').value;
    try {
        const metaRes = await fetch(`${BASE_URL}/api/meta/${gameId}`);
        if (!metaRes.ok) return;
        const m = await metaRes.json();

        // デフォルト表示範囲: 先頭から 300 フレーム
        document.getElementById('frameStartInput').value = m.frame_range.start;
        document.getElementById('frameEndInput').value   =
            Math.min(m.frame_range.start + 300, m.frame_range.end);
    } catch (_) {
        // サーバー未起動の場合は何もしない
    }
}

// 試合IDが変わったらフレーム範囲のデフォルトを更新する
document.getElementById('gameIdInput').addEventListener('change', initUI);
document.getElementById('fetchDataBtn').addEventListener('click', fetchAndAnimate);
window.addEventListener('load', initUI);

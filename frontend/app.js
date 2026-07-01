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
 * あわせて Top 10 ハイライトも読み込む。
 * サーバーが起動していない場合は静かに失敗する。
 */
async function initUI() {
    const gameId = document.getElementById('gameIdInput').value;
    try {
        const metaRes = await fetch(`${BASE_URL}/api/meta/${gameId}`);
        if (!metaRes.ok) return;
        meta = await metaRes.json();

        document.getElementById('frameStartInput').value = meta.frame_range.start;
        document.getElementById('frameEndInput').value   =
            Math.min(meta.frame_range.start + 300, meta.frame_range.end);

        // cfCanvas の高さをピッチ比率に合わせる
        const cfCanvas = document.getElementById('cfCanvas');
        cfCanvas.height = Math.round(cfCanvas.width * meta.pitch.width / meta.pitch.length);

        await loadTopEvents(gameId);
    } catch (_) {
        // サーバー未起動の場合は何もしない
    }
}

// ================================================================== //
// Top 10 ハイライトパネル
// ================================================================== //

/**
 * /api/top_events から Top 10 を取得してリストを描画する。
 */
async function loadTopEvents(gameId) {
    try {
        const res = await fetch(`${BASE_URL}/api/top_events/${gameId}`);
        if (!res.ok) return;
        const events = await res.json();
        document.getElementById('topLoadingMsg').style.display = 'none';
        renderTopList(events, gameId);
    } catch (_) {}
}

function renderTopList(events, gameId) {
    const container = document.getElementById('topEventsList');
    if (!events.length) {
        container.innerHTML = '<p style="color:#999">データなし</p>';
        return;
    }

    const table = document.createElement('table');
    table.innerHTML = `
        <thead>
            <tr>
                <th>#</th><th>選手</th><th>スコア</th>
                <th>反事実PC</th><th>イベント</th><th>フレーム</th>
            </tr>
        </thead>
        <tbody>
            ${events.map(e => `
                <tr class="data-row"
                    data-event-id="${e.event_id}"
                    data-player-id="${e.player_id}"
                    data-score="${e.importance_score}"
                    data-marginal="${e.marginal_pc}"
                    data-type="${e.event_type}"
                    data-frame="${e.frame_id}">
                    <td>${e.rank}</td>
                    <td><strong>${e.player_id}</strong></td>
                    <td>${(e.importance_score * 100).toFixed(1)}%</td>
                    <td>+${e.marginal_pc.toFixed(3)}</td>
                    <td>${e.event_type}</td>
                    <td>${e.frame_id}</td>
                </tr>
            `).join('')}
        </tbody>
    `;

    table.querySelectorAll('tr.data-row').forEach(row => {
        row.addEventListener('click', () => {
            table.querySelectorAll('tr.data-row').forEach(r => r.classList.remove('selected'));
            row.classList.add('selected');
            fetchAndDrawCounterfactual(
                gameId,
                parseInt(row.dataset.eventId),
                row.dataset.playerId,
                {
                    score:    parseFloat(row.dataset.score),
                    marginal: parseFloat(row.dataset.marginal),
                    type:     row.dataset.type,
                    frame:    parseInt(row.dataset.frame),
                }
            );
        });
    });

    container.innerHTML = '';
    container.appendChild(table);
}

/**
 * 選手クリック時: /api/counterfactual を叩いて差分ヒートマップを描画する。
 * 計算に数秒かかるため、ローディング表示を出してから実行する。
 */
async function fetchAndDrawCounterfactual(gameId, eventId, playerId, info) {
    const cfInfo    = document.getElementById('cfInfo');
    const cfLoading = document.getElementById('cfLoading');
    const cfCanvas  = document.getElementById('cfCanvas');

    cfLoading.classList.add('visible');
    cfInfo.innerHTML = `<span style="color:#666">${playerId} の反事実計算中...</span>`;

    try {
        const res = await fetch(
            `${BASE_URL}/api/counterfactual/${gameId}?event_id=${eventId}&player_id=${playerId}`
        );
        if (!res.ok) throw new Error(`API エラー: ${res.status}`);
        const data = await res.json();

        cfInfo.innerHTML = `
            <strong>${playerId}</strong>
            &nbsp;·&nbsp; ${info.type || 'イベント'}
            &nbsp;·&nbsp; フレーム ${info.frame}
            &nbsp;&nbsp;
            スコア: <strong>${(info.score * 100).toFixed(1)}%</strong>
            &nbsp;|&nbsp;
            反事実 PC 貢献: <strong>+${info.marginal.toFixed(3)}</strong>
            <br>
            <small>オレンジが濃いエリアほど、この選手によって生み出された（または守られた）空間です</small>
        `;

        drawCounterfactual(cfCanvas, data);
    } catch (err) {
        cfInfo.innerHTML = `<span style="color:red">エラー: ${err.message}</span>`;
    } finally {
        cfLoading.classList.remove('visible');
    }
}

/**
 * 反事実ピッチコントロール差分ヒートマップを描画する。
 *
 * - オレンジのグラデーション: diff_grid の正の値（この選手の貢献エリア）
 * - 対象選手: 黄色の大きい円 + ラベル
 * - 他の選手: チームカラーの小さい半透明円
 * - ボール: 白い円
 *
 * 座標系は to_single_playing_direction 適用済みのメートル値。
 */
function drawCounterfactual(cfCanvas, data) {
    const ctx  = cfCanvas.getContext('2d');
    const w    = cfCanvas.width;
    const h    = cfCanvas.height;

    // ピッチ背景
    ctx.fillStyle = '#4CAF50';
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = 'rgba(255,255,255,0.6)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(w / 2, 0);
    ctx.lineTo(w / 2, h);
    ctx.stroke();
    ctx.strokeRect(0, 0, w, h);

    // diff_grid のヒートマップ描画
    const grid   = data.diff_grid;
    const nRows  = grid.length;
    const nCols  = grid[0].length;
    const maxVal = Math.max(...grid.flat(), 0.001);
    const cellW  = w / nCols;
    const cellH  = h / nRows;

    for (let i = 0; i < nRows; i++) {
        for (let j = 0; j < nCols; j++) {
            const val = grid[i][j];
            if (val <= 0.001) continue;
            // 正規化した値を透明度に変換（最大値で 0.85 になるよう調整）
            const alpha = Math.min(val / maxVal, 1.0) * 0.85;
            ctx.fillStyle = `rgba(255, 110, 0, ${alpha})`;
            ctx.fillRect(j * cellW, i * cellH, cellW + 1, cellH + 1);
        }
    }

    // 座標変換（to_single_playing_direction 空間 → canvas ピクセル）
    // xgrid の端からピッチ境界を復元する（セル中心からセル幅/2 を引いた点が端）
    const halfLen = meta ? meta.pitch.length / 2 : 53;
    const halfWid = meta ? meta.pitch.width  / 2 : 34;

    function toCF(x, y) {
        return [
            Math.min(Math.max((x + halfLen) / (halfLen * 2) * w, 0), w),
            Math.min(Math.max((y + halfWid) / (halfWid * 2) * h, 0), h),
        ];
    }

    // 全選手を描画
    const teamDefs = [
        { prefix: 'Home', dataKey: 'home_data', color: '#e74c3c' },
        { prefix: 'Away', dataKey: 'away_data', color: '#3498db' },
    ];

    for (const td of teamDefs) {
        const teamData = data[td.dataKey];
        if (!teamData) continue;

        const playerKeys = Object.keys(teamData)
            .filter(k =>
                k.startsWith(td.prefix + '_') &&
                k.endsWith('_x') &&
                !k.endsWith('_vx')
            );

        for (const key of playerKeys) {
            const pid = key.slice(td.prefix.length + 1, -2);
            const x   = teamData[`${td.prefix}_${pid}_x`];
            const y   = teamData[`${td.prefix}_${pid}_y`];
            if (x === 0 && y === 0) continue;

            const [cx, cy]  = toCF(x, y);
            const fullId    = `${td.prefix}_${pid}`;
            const isTarget  = fullId === data.player_id;

            if (isTarget) {
                // 対象選手: 白いリング + 黄色の大きい円 + ラベル
                ctx.beginPath();
                ctx.arc(cx, cy, 15, 0, Math.PI * 2);
                ctx.strokeStyle = 'white';
                ctx.lineWidth   = 3;
                ctx.stroke();

                ctx.beginPath();
                ctx.arc(cx, cy, 10, 0, Math.PI * 2);
                ctx.fillStyle = 'yellow';
                ctx.fill();

                ctx.fillStyle  = '#222';
                ctx.font       = 'bold 11px sans-serif';
                ctx.textAlign  = 'center';
                ctx.textBaseline = 'bottom';
                ctx.fillText(fullId, cx, cy - 18);
                ctx.textBaseline = 'alphabetic';
            } else {
                ctx.globalAlpha = 0.65;
                ctx.beginPath();
                ctx.arc(cx, cy, 5, 0, Math.PI * 2);
                ctx.fillStyle = td.color;
                ctx.fill();
                ctx.globalAlpha = 1.0;
            }
        }
    }

    // ボール（白い円）
    const [bx, by] = toCF(data.ball_pos[0], data.ball_pos[1]);
    ctx.beginPath();
    ctx.arc(bx, by, 5, 0, Math.PI * 2);
    ctx.fillStyle   = 'white';
    ctx.strokeStyle = '#333';
    ctx.lineWidth   = 1.5;
    ctx.fill();
    ctx.stroke();
}

// 試合IDが変わったらフレーム範囲とTop10を更新する
document.getElementById('gameIdInput').addEventListener('change', initUI);
document.getElementById('fetchDataBtn').addEventListener('click', fetchAndAnimate);
window.addEventListener('load', initUI);

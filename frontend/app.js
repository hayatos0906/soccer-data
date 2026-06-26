const canvas = document.getElementById('pitchCanvas');
const ctx = canvas.getContext('2d');
const scale = 10;

// ピッチの描画（背景）
function drawPitch() {
    ctx.fillStyle = '#4CAF50';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = 'white';
    ctx.lineWidth = 2;
    // センターライン等
    ctx.beginPath();
    ctx.moveTo(canvas.width / 2, 0);
    ctx.lineTo(canvas.width / 2, canvas.height);
    ctx.stroke();
}

// 選手を描画する関数
function drawFrame(frameData) {
    drawPitch();

    // ホームチーム（赤）
    ctx.fillStyle = 'red';
    for (let i = 1; i <= 14; i++) {
        const x = frameData.home_data[`Home_${i}_x`];
        const y = frameData.home_data[`Home_${i}_y`];
        if (x && !isNaN(x)) {
            ctx.beginPath();
            ctx.arc((x + 52.5) * scale, (y + 34) * scale, 5, 0, Math.PI * 2);
            ctx.fill();
        }
    }

    // ★Awayチーム（青）を追加！
    ctx.fillStyle = 'blue';
    for (let i = 1; i <= 14; i++) {
        const x = frameData.away_data[`Away_${i}_x`];
        const y = frameData.away_data[`Away_${i}_y`];
        if (x && !isNaN(x)) {
            ctx.beginPath();
            ctx.arc((x + 52.5) * scale, (y + 34) * scale, 5, 0, Math.PI * 2);
            ctx.fill();
        }
    }
}

// アニメーションループ
document.getElementById('fetchDataBtn').addEventListener('click', async () => {
    const response = await fetch('http://127.0.0.1:8000/api/tracking/2?frame_start=1&frame_end=100');
    const data = await response.json();

    let frame = 0;
    function animate() {
        if (frame < data.home_data.length) {
            // ホームとアウェイ両方のデータを渡す
            drawFrame({
                home_data: data.home_data[frame],
                away_data: data.away_data[frame]
            });
            frame++;
            setTimeout(animate, 40);
        }
    }
    animate();
});
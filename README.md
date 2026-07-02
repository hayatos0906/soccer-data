# soccer-data

Metrica Sports 形式のトラッキングデータ（Sample Game 2）を可視化する Web アプリ。  
ピッチアニメーション、選手重要度ハイライト、反事実ピッチコントロール（Top 10）を表示する。

**実行環境: ローカルのみ**（Docker + ブラウザ）。本番デプロイ・外部 DB は未対応。

| 項目 | 内容 |
|------|------|
| 対象試合 | `game_id = 2` のみ |
| 同梱データ | `player_importance.csv`（分析結果） |
| 要手動配置 | Metrica 生 CSV 3 ファイル（下記） |
| 外部サービス | 不要（Supabase / `.env` なしで起動可） |

---

## 必要環境

- [Docker](https://docs.docker.com/get-docker/)（Compose 同梱）
- Python 3（フロントの静的配信のみ。標準ライブラリで足りる）

---

## セットアップ

### 1. クローン

```bash
git clone https://github.com/hayatos0906/soccer-data.git
cd soccer-data
```

### 2. Metrica 生データを配置（初回のみ）

[Metrica sample data / Sample_Game_2](https://github.com/metrica-sports/sample-data/tree/master/data/Sample_Game_2) から次の 3 ファイルをダウンロードし、リポジトリ内に置く。

```text
backend/data/Sample_Game_2/
├── Sample_Game_2_RawTrackingData_Home_Team.csv
├── Sample_Game_2_RawTrackingData_Away_Team.csv
└── Sample_Game_2_RawEventsData.csv
```

未配置の場合: API は起動するが、アニメーション・反事実計算はモックデータになる。

### 3. バックエンド起動

リポジトリルートで実行:

```bash
docker compose -f backend/compose.analytics.yml up --build
```

- API: http://127.0.0.1:8000
- 死活確認: `curl http://127.0.0.1:8000/health`

### 4. フロント起動（別ターミナル）

```bash
cd frontend
python3 -m http.server 5500
```

- UI: http://127.0.0.1:5500  
- `8000` は API 用。ブラウザで開くのは `5500`。

---

## リポジトリ構成

```text
soccer-data/
├── frontend/          # 静的 UI（index.html, app.js）
├── backend/
│   ├── src/main.py    # API 本体（Docker が起動）
│   ├── data/          # CSV（生データは .gitignore）
│   └── compose.analytics.yml
└── .github/workflows/ # backend 変更時: ruff, mypy
```

`backend/api.py` は旧入口。Docker の正本は `src.main:app`。

---

## データについて

- 生トラッキング CSV は [Metrica Sports](https://github.com/metrica-sports/sample-data) のサンプルデータを利用する。
- リポジトリに含めない（容量・再配布の都合）。各自ダウンロードが必要。

---

## 開発

```bash
# リント・型チェック（CI と同じ）
pip install -r backend/requirements.txt
ruff check backend/src/
mypy backend/src/ --ignore-missing-imports
```

詳細仕様: `backend/DESIGN_DOC.md`

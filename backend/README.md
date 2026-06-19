# バックエンド＆分析班 開発手順書

2年生へ：環境構築とタスクの実装手順です。仕様の詳細は `backend/DESIGN_DOC.md` を確認してください。

## 🚀 1. 開発の始め方（初期セットアップ）
1. 分析班の誰か1人のアカウントで Supabase（無料）にプロジェクトを作成し、メンバー全員（先輩含む）を招待してください。
2. `backend/.env.example` をコピーして `backend/.env` を作成し、Supabaseの `SUPABASE_URL` と `SUPABASE_KEY` を書き込んでください。
   ```bash
   cp backend/.env.example backend/.env
   ```
3. ルートディレクトリにある「2年生用Cursorプロンプト」をCursorに貼り付けて、初期バグの修正とセットアップを完了させてください。

## 🐳 2. コンテナの起動方法
セットアップ完了後、以下のコマンドでFastAPI（`http://localhost:8000`）が起動します。
```bash
docker-compose -f backend/compose.analytics.yml up --build
```
※ファイルを書き換えると自動で即時反映（ホットリロード）されます。

## 🛠️ 3. 実装タスク
- `src/parser.py` の中身を埋める（CSVの読み込みと平滑化ノイズ除去）。
- `src/database.py` の中身を埋める（Supabaseへのデータ保存）。

## ⚠️ 4. 絶対ルール
- `src/engine.py` は先輩の聖域です。**1文字も変更しないでください。**
- コードをプッシュする前に、GitHub CI（型チェック・Linter）が緑（パス）になることを必ず確認してください。赤エラーが出たら、メッセージをCursorに投げて全て修正させてからプッシュすること。
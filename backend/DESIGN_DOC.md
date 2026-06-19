# プロジェクト設計書：サッカートラッキングデータ可視化システム (Analytics Backend)

## 1. プロジェクト概要
Metrica Sportsのトラッキングデータ（Match 1/2）をブラウザ上で可視化し、戦術分析を支援する。
空間支配率の計算には `LaurieOnTracking` (Pitch Control) モデルを採用する。

## 2. 技術スタック
- バックエンド: Python 3.10 / FastAPI
- データベース / キャッシュ: Supabase (無料プラン / 1つのDBをチームで共有)
- 開発環境: Docker / Docker Compose (ホットリロード対応)
- 品質管理: Ruff (Linter) / mypy (静的型チェック)
- デプロイ: 保留（ローカル `localhost:8000` を正本とする）

## 3. セキュリティ・環境変数方針
- SupabaseのURL、APIキー等の秘密情報は、GitHubのコード内（Dockerfileやmain.py等）に直書きすることを**厳禁**とする。
- すべてコンテナ内の環境変数から読み込む構造とし、ローカルでは `.env` ファイル（Git管理外）にて秘匿管理する。

## 4. フロント合流・エッジケース制約（重要）
- **CORS仕様:** フロント（Next.js）からのCookieや認証情報を伴う通信を想定し、`allow_credentials=True` の時は `allow_origins` に `*` を指定せず、適切なオリジンを設定（または環境変数化）すること。
- **ファイル受取:** `POST /analyze/{match_id}` は、サーバー内パス文字列（file_path: str）ではなく、ブラウザからのアップロードに対応するため **`UploadFile` (multipart/form-data)** で受けること。
- **データ処理:** 数万行のCSV処理に伴うOOM（メモリ枯渇）や、同期ブロッキングによるハングアップを防ぐため、適切なエラーハンドリングと効率的なデータ処理を行うこと。

## 5. 関数インターフェース定義 (聖域の分離)
- `src/parser.py`: `parse_metrica_csv(file_to_upload) -> tuple[pd.DataFrame, pd.DataFrame]`
- `src/database.py`: `save_analysis_cache(match_id: str, frame_id: int, result_json: dict, supabase_url: str, supabase_key: str) -> bool`
- `src/engine.py`: `calculate_pitch_control(...)` ※先輩の担当聖域（2年生・AIは変更禁止）
# backend

手順・データ配置・アプリ概要は [ルート README](../README.md) を参照。

```bash
# リポジトリルートから
docker compose -f backend/compose.analytics.yml up --build
```

エントリポイント: `uvicorn src.main:app`（`compose.analytics.yml`）

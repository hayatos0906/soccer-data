from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api import router

app = FastAPI(title="Soccer Tracking API")

# フロントエンドからの通信を許可する設定（CORS対策）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 本番環境ではドメインを指定します
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# APIのルーティングを読み込む
app.include_router(router)

@app.get("/")
def read_root():
    return {"message": "Soccer Tracking API is running!"}
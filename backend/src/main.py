import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from src.database import save_analysis_cache
from src.parser import parse_metrica_csv

app = FastAPI()

_default_cors_origins = "http://localhost:3000,http://127.0.0.1:3000"
_cors_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", _default_cors_origins).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise HTTPException(
            status_code=500,
            detail=f"環境変数 {name} が未設定です。backend/.env を確認してください。",
        )
    return value


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze/{match_id}")
async def run_analysis(
    match_id: str,
    file: UploadFile = File(...),
) -> dict[str, str]:
    """
    フロントやアナリストから叩かれるメインAPI。
    CSVは multipart/form-data の UploadFile として受け取る。
    """
    supabase_url = _require_env("SUPABASE_URL")
    supabase_key = _require_env("SUPABASE_KEY")

    home_df, away_df = parse_metrica_csv(file)
    # TODO: 先輩が engine.py の数理ロジックをここに挟む
    _ = home_df, away_df

    success = save_analysis_cache(
        match_id,
        1,
        {"message": "temporary"},
        supabase_url,
        supabase_key,
    )
    return {"status": "success" if success else "failed"}

FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# 開発時はホットリロードを有効化するために、CMDはcompose側で上書きします
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
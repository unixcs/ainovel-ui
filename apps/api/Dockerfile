FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app
COPY app ./app
RUN pip install --no-cache-dir \
    fastapi==0.116.2 \
    uvicorn[standard]==0.35.0 \
    cryptography==45.0.7 \
    httpx==0.28.1 \
    docker==7.2.0
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

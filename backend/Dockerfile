FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    && rm -rf /var/lib/postgresql/data \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first for Docker layer caching.
# requirements.txt is derived from pyproject.toml; changes to source code
# alone won't invalidate this layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

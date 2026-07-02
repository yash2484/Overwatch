FROM python:3.12-slim

WORKDIR /app

# rasterio's bundled GDAL needs libexpat at runtime; slim doesn't ship it
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[dev]"

COPY tests ./tests

EXPOSE 8000
CMD ["uvicorn", "overwatch.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

WORKDIR /app

# Wheels only where possible; psycopg2-binary and numpy both ship them for
# slim-bookworm, so no build toolchain is needed in the image.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

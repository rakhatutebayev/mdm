FROM python:3.12-slim

# Production backend serves prebuilt agent artifacts; curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
# Linux proxy-agent bootstrap (TZ §5): GET /api/v1/agent/bootstrap/install.sh
RUN mkdir -p /app/agent_bootstrap
COPY proxy-agent/install.sh /app/agent_bootstrap/install-proxy-agent.sh

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

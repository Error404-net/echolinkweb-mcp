FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG REPO_URL=https://github.com/Error404-net/echolinkweb-mcp.git
ARG REPO_REF=main

RUN git clone --branch "${REPO_REF}" --depth 1 "${REPO_URL}" .

RUN pip install --no-cache-dir -r requirements.txt

ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8765

EXPOSE 8765

CMD ["python3", "run_http.py"]

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple .
COPY clients/core ./clients/core
COPY clients/web ./clients/web
COPY deploy/tencent/models/action_model_2025-26.json ./data/derived/action_model_2025-26.json
COPY deploy/tencent/models/lever_limits_2025-26.json ./data/derived/lever_limits_2025-26.json
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["hoopformer", "serve", "--data-dir", "/app/data", "--season", "2025-26", "--rosters", "", "--home", "90S", "--away", "00S", "--host", "0.0.0.0", "--port", "8000", "--use", "auto"]

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY app ./app
COPY examples ./examples
COPY scripts ./scripts

RUN uv sync --extra dev

CMD ["uv", "run", "--extra", "dev", "agentops", "run", "--repo", "examples/sample_fastapi_app", "--task", "Add request logging middleware"]

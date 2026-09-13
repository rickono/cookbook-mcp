FROM --platform=$BUILDPLATFORM python:3.12-slim-bookworm AS requirements
WORKDIR /requirements
RUN pip install --no-cache-dir uv==0.11.14
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils djvulibre-bin && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=requirements /requirements/requirements.txt /tmp/requirements.txt
RUN python -m venv .venv && .venv/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN .venv/bin/pip install --no-cache-dir --no-deps .
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --create-home cookbook
USER cookbook
ENTRYPOINT ["cookbook"]
CMD ["supervise"]

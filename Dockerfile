FROM --platform=$BUILDPLATFORM python:3.12-slim-bookworm AS requirements
WORKDIR /requirements
RUN pip install --no-cache-dir uv==0.11.14
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt

# Official Linux/amd64 30.2 release; checksum pins the downloaded archive.
ADD --checksum=sha256:cd791605e7c6cc7be457794f534cd4b9f9d361781adb10e40020efc22840ebc3 https://dl.typesense.org/releases/30.2/typesense-server-30.2-linux-amd64.tar.gz /tmp/typesense.tar.gz
RUN python -c "import tarfile; t=tarfile.open('/tmp/typesense.tar.gz'); m=next(m for m in t.getmembers() if m.isfile() and m.name.rsplit('/',1)[-1]=='typesense-server'); open('/tmp/typesense-server','wb').write(t.extractfile(m).read())"

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils djvulibre-bin && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=requirements /requirements/requirements.txt /tmp/requirements.txt
COPY --from=requirements --chmod=755 /tmp/typesense-server /usr/local/bin/typesense-server
RUN python -m venv .venv && .venv/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN .venv/bin/pip install --no-cache-dir --no-deps .
# Source-free Linux smoke check: owned loopback keyword server, no embedding schema.
RUN .venv/bin/python - <<'PYSMOKE'
from tempfile import TemporaryDirectory
from cookbook.book_search import BookSearch
with TemporaryDirectory() as root:
    engine = BookSearch('/usr/local/bin/typesense-server', root)
    try:
        engine.start()
        assert engine.call('GET', '/health')['ok']
    finally:
        engine.close()
PYSMOKE
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --create-home cookbook
USER cookbook
ENTRYPOINT ["cookbook"]
CMD ["supervise"]

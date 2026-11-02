FROM python:3.12.8 AS builder

WORKDIR /workdir

# https://github.com/hadolint/hadolint/wiki/DL4006
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN pip install --no-cache-dir uv==0.11.6 \
    && curl -fsSL https://raw.githubusercontent.com/pressly/goose/master/install.sh | sh

COPY pyproject.toml uv.lock ./

ENV UV_HTTP_TIMEOUT=600

RUN uv sync --frozen --no-install-project --no-dev

FROM python:3.12.8-slim AS prod

ENV TZ=Asia/Taipei

WORKDIR /workdir

COPY --from=builder /workdir/.venv/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/goose /usr/local/bin/goose
COPY . .

ENTRYPOINT [ "/workdir/docker-entrypoint.sh" ]

CMD ["python", "main.py"]

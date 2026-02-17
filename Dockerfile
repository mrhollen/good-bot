FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates openssh-client \
    && groupadd --gid 10001 goodbot \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash goodbot \
    && mkdir -p /workspace /tmp/good_bot \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/good-bot-seed
COPY docker-entrypoint.sh /usr/local/bin/good-bot-entrypoint

RUN chmod +x /usr/local/bin/good-bot-entrypoint \
    && chown -R goodbot:goodbot /workspace /tmp/good_bot /opt/good-bot-seed

WORKDIR /workspace
USER goodbot

ENTRYPOINT ["/usr/local/bin/good-bot-entrypoint"]

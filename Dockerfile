FROM python:3.12.6-alpine3.20

RUN addgroup -g 2000 appgroup && \
    adduser -u 1000 -G appgroup -s /bin/sh -D appuser

COPY requirements.txt requirements.txt

RUN pip install --no-cache-dir -r requirements.txt && \
    chown -R appuser:appgroup /usr/local/lib/python3.12/site-packages

USER appuser

COPY --chown=appuser:appgroup src .

ENTRYPOINT ["kopf", "run", "main.py"]
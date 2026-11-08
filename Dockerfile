# A Good Fit API: production image (gunicorn behind the stack's nginx).

# The React business portal, built here so the server needs no Node and the
# whole thing stays one deployment. Django serves it from /static/portal/.
FROM node:22-alpine AS portal
WORKDIR /portal
COPY portal/package.json portal/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY portal/ ./
RUN npm run build

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=goodfit_api.settings.production

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Non-root user; media/static/logs are volumes owned by it.
RUN useradd --uid 1000 --create-home app

# Readable by the app whatever the permissions were on the machine it was
# copied from.
COPY --chown=app:app . .
COPY --from=portal --chown=app:app /portal/dist /app/portal/dist
RUN mkdir -p /app/media /app/staticfiles /app/logs \
    && chown -R app:app /app/media /app/staticfiles /app/logs \
    && chmod -R u+rwX,go+rX /app && chmod +x /app/deploy/entrypoint.sh
USER app

EXPOSE 8000
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["gunicorn", "goodfit_api.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--worker-class", "gthread", "--workers", "3", "--threads", "4", \
     "--timeout", "60", "--max-requests", "2000", "--max-requests-jitter", "200", \
     "--access-logfile", "-", "--error-logfile", "-"]

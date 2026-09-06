FROM python:3.11-slim

# Headless Chromium for the admin scraper (vendored fetchall). Remove the playwright line to build a
# smaller image without scraping support; the app then shows "scraping not available" in the console.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN useradd -m app \
    && mkdir -p app/static/uploads instance/private_uploads instance/scraper_exports instance/scraper_sessions \
    && chown -R app:app /app /ms-playwright
USER app

EXPOSE 8080
CMD gunicorn run:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 --log-level info

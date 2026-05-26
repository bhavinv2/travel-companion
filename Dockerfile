FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p app/static/uploads
EXPOSE 8080
CMD gunicorn run:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 --log-level debug

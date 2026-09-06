web: flask --app run db upgrade && gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --log-level info

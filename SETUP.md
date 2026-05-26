# Connecting Desis – GCP Setup Guide

## 1. Run Locally (No GCP needed)

```bash
cd connecting-desis
python -m venv venv
source venv/bin/activate          # Mac/Linux
# venv\Scripts\activate           # Windows

pip install -r requirements.txt

# Copy env file and fill in values
cp .env.example .env
# Edit .env — for local dev, use SQLite by leaving DATABASE_URL as sqlite:///dev.db

# Initialize database
flask db init
flask db migrate -m "Initial migration"
flask db upgrade

# Run the app
python run.py
# Visit http://localhost:5000
```

## 2. Create Your First Admin User

```bash
# With the app running, open a Flask shell:
flask shell

>>> from app import db
>>> from app.models import User
>>> u = User.query.filter_by(email='your@email.com').first()
>>> u.is_admin = True
>>> db.session.commit()
>>> exit()
```

---

## 3. GCP Setup (Production)

### Step 1: Create GCP Project
```bash
gcloud projects create connecting-desis-prod
gcloud config set project connecting-desis-prod
```

### Step 2: Enable APIs
```bash
gcloud services enable \
  run.googleapis.com \
  sql-component.googleapis.com \
  sqladmin.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  containerregistry.googleapis.com
```

### Step 3: Create Cloud SQL PostgreSQL Instance
```bash
gcloud sql instances create connecting-desis-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-central1

# Create the database
gcloud sql databases create connectingdesis --instance=connecting-desis-db

# Create a user
gcloud sql users create appuser --instance=connecting-desis-db --password=STRONG_PASSWORD
```

### Step 4: Store Secrets in Secret Manager
```bash
# Store each secret (one command per secret):
echo -n "your-flask-secret-key" | gcloud secrets create flask-secret-key --data-file=-
echo -n "postgresql://appuser:STRONG_PASSWORD@/connectingdesis?host=/cloudsql/PROJECT_ID:us-central1:connecting-desis-db" | gcloud secrets create database-url --data-file=-
echo -n "your-gmail-app-password" | gcloud secrets create mail-password --data-file=-
```

> **DATABASE_URL for Cloud SQL:** Use the Unix socket format above — Cloud Run connects via the Cloud SQL Auth Proxy automatically.

### Step 5: Connect Cloud Run to Cloud SQL
The `cloudbuild.yaml` already includes `--add-cloudsql-instances` and `--set-secrets` flags. Cloud Run will automatically mount the Cloud SQL Auth Proxy socket when deployed.

### Step 6: Grant Secret Manager Access to Cloud Run
```bash
# Get the Cloud Run service account
PROJECT_NUMBER=$(gcloud projects describe PROJECT_ID --format='value(projectNumber)')
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud secrets add-iam-policy-binding flask-secret-key \
  --member="serviceAccount:${SERVICE_ACCOUNT}" --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding database-url \
  --member="serviceAccount:${SERVICE_ACCOUNT}" --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding mail-password \
  --member="serviceAccount:${SERVICE_ACCOUNT}" --role="roles/secretmanager.secretAccessor"
```

### Step 7: Set Up Cloud Build Trigger (Auto-Deploy from GitHub)
```bash
# Connect your GitHub repo to Cloud Build in the GCP Console:
# Cloud Build → Triggers → Connect Repository → GitHub → Select your repo
# Set trigger to run on push to main branch
# Build configuration: cloudbuild.yaml
```

Or deploy manually:
```bash
gcloud builds submit --config cloudbuild.yaml
```

### Step 8: Run Database Migrations on Cloud Run
```bash
# One-time: run migrations after first deploy
gcloud run jobs create run-migrations \
  --image gcr.io/PROJECT_ID/connecting-desis:latest \
  --region us-central1 \
  --set-cloudsql-instances PROJECT_ID:us-central1:connecting-desis-db \
  --set-secrets DATABASE_URL=database-url:latest \
  --command "flask,db,upgrade"

gcloud run jobs execute run-migrations --region us-central1
```

### Step 9: Connect Custom Domain
```bash
# In GCP Console: Cloud Run → your service → Custom Domains → Add mapping
# Or via CLI:
gcloud run domain-mappings create \
  --service connecting-desis \
  --domain connectingdesis.com \
  --region us-central1

# Then add the DNS records shown (A/AAAA records) to your domain registrar
```

---

## 4. File Uploads: Local → Google Cloud Storage

When you're ready to store uploaded photos/files in GCS instead of local disk:

1. Create a GCS bucket: `gcloud storage buckets create gs://connecting-desis-uploads`
2. Install `google-cloud-storage`: `pip install google-cloud-storage`
3. Update `app/routes/auth.py` and `app/routes/chat.py` to use `storage_client.bucket('connecting-desis-uploads').blob(filename).upload_from_file(...)` instead of `photo.save(upload_path)`
4. Set `photo_url` to the public GCS URL: `https://storage.googleapis.com/connecting-desis-uploads/{filename}`

---

## 5. Email (Gmail SMTP) Setup

1. Go to your Gmail account → Security → Enable 2FA
2. App Passwords → Create a new app password for "Mail"
3. Use that 16-character password as `MAIL_PASSWORD` in your secrets

For production volume, switch to **SendGrid** or **Mailgun** (better deliverability):
- Change `MAIL_SERVER=smtp.sendgrid.net`, `MAIL_PORT=587`, `MAIL_USERNAME=apikey`, `MAIL_PASSWORD=your-sendgrid-api-key`

---

## 6. Environment Variables Summary

| Variable | Where to set | Example |
|---|---|---|
| `FLASK_SECRET_KEY` | Secret Manager | random 50-char string |
| `DATABASE_URL` | Secret Manager | postgresql://... (Cloud SQL socket format) |
| `MAIL_USERNAME` | Secret Manager | noreply@connectingdesis.com |
| `MAIL_PASSWORD` | Secret Manager | Gmail app password |
| `GOOGLE_OAUTH_CLIENT_ID` | Secret Manager | from Google Cloud Console |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Secret Manager | from Google Cloud Console |

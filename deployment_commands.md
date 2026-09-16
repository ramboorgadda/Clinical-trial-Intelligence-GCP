
### Complete Command Reference — MOSAIC Deployment

---

### Part 1 — Docker Commands

#### Build the image

bash

```bash
docker buildx build \
  --platform linux/amd64 \
  --tag gcr.io/mosaic-clinical-trials/mosaic-api:latest \
  --file deployment/Dockerfile \
  --push \
.
```

**What this does:**

* `docker buildx build` — builds a Docker image using BuildKit (more powerful than plain `docker build`)
* `--platform linux/amd64` — forces AMD64 architecture even on Apple Silicon Mac. Without this Cloud Run crashes with "exec format error"
* `--tag gcr.io/...` — names the image and tells Docker where to push it. `gcr.io` is Google Container Registry
* `--file deployment/Dockerfile` — which Dockerfile to use
* `--push` — builds AND pushes to GCR in one command. Without this the image stays local and Cloud Run cannot access it
* `.` — the build context. Everything in the current directory is available to the Dockerfile

---

#### Configure Docker to authenticate with GCR

bash

```bash
gcloud auth configure-docker
```

**What this does:**

Tells Docker how to authenticate when pushing to `gcr.io`. Without this, `docker push` to GCR fails with "unauthorized". Only needs to be run once per machine.

---

#### Test the image locally before deploying

bash

```bash
docker run -p 8000:8000 --env-file .env mosaic-api
```

**What this does:**

* Runs the container locally on your Mac
* `-p 8000:8000` maps port 8000 on your Mac to port 8000 inside the container
* `--env-file .env` injects your local `.env` variables into the container
* Lets you test the full API at `http://localhost:8000/docs` before deploying to GCP

---

### Part 2 — GCP Authentication Commands

#### Login to GCP

bash

```bash
gcloud auth login
```

Authenticates the `gcloud` CLI with your Google account. Opens a browser for login. Must be done before any other gcloud command works.

---

#### Set application default credentials for Python

bash

```bash
gcloud auth application-default login
```

Separate from `gcloud auth login`. This gives Python libraries (google-cloud-storage, asyncpg via Cloud SQL) the credentials they need to make authenticated GCP API calls. Without this, Python code gets "credentials not found" errors.

---

#### Set quota project for Python libraries

bash

```bash
gcloud auth application-default set-quota-project mosaic-clinical-trials
```

Tells Python libraries which GCP project to bill API calls to. Required when switching between projects.

---

#### Set active project for gcloud CLI

bash

```bash
gcloud config set project mosaic-clinical-trials
```

All subsequent gcloud commands run against this project. Think of it as `cd` but for GCP projects.

---

#### Verify which project Python sees

bash

```bash
python3 -c "import google.auth; creds, project = google.auth.default(); print(f'Auth OK — Project: {project}')"
```

Confirms Python libraries are authenticated and pointing to the right project. Run this whenever you are unsure about authentication state.

---

### Part 3 — GCP Project and API Commands

#### List all projects

bash

```bash
gcloud projects list
```

Shows all GCP projects your account has access to. Useful to confirm the project exists before running any commands.

---

#### List enabled APIs

bash

```bash
gcloud services list --enabled --project=mosaic-clinical-trials
```

Shows every API enabled on the project. We look for `sqladmin.googleapis.com` and `storage.googleapis.com` to confirm the services we need are active.

---

#### Enable required APIs

bash

```bash
gcloud services enable\
  run.googleapis.com \
  cloudbuild.googleapis.com \
  containerregistry.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  --project=mosaic-clinical-trials
```

Activates the GCP services we need. Safe to run multiple times — enabling an already-enabled API does nothing. APIs must be enabled before you can use them — even creating a Cloud SQL instance fails if the sqladmin API is not enabled.

---

### Part 4 — Cloud SQL Commands

#### Create the PostgreSQL instance

bash

```bash
gcloud sql instances create clinical-trial-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --zone=us-central1-f \
  --project=mosaic-clinical-trials
```

**What each flag does:**

* `--database-version=POSTGRES_15` — PostgreSQL 15 (supports pgvector)
* `--tier=db-f1-micro` — smallest and cheapest instance type (~$15/month). Enough for our workload
* `--zone=us-central1-f` — specific zone within us-central1. We specify the zone (not region) to avoid PENDING_CREATE issues we encountered

---

#### Create the database inside the instance

bash

```bash
gcloud sql databases create clinical_trial_db \
  --instance=clinical-trial-db \
  --project=mosaic-clinical-trials
```

Creates a named database inside the instance. The instance is the server. The database is the storage space inside that server where tables live.

---

#### Create the database user

bash

```bash
gcloud sql users create mosaic_user \
  --instance=clinical-trial-db \
  --password=YourNewSecurePassword123 \
  --project=mosaic-clinical-trials
```

Creates the application user. Our Python code connects as this user — not as postgres (the admin user).

---

#### Reset a user password

bash

```bash
gcloud sql users set-password mosaic_user \
  --instance=clinical-trial-db \
  --password=YourNewSecurePassword123 \
  --project=mosaic-clinical-trials
```

Resets the password when you forget it. We used this when we could not recall the original password.

---

#### Whitelist IP addresses

bash

```bash
gcloud sql instances patch clinical-trial-db \
  --authorized-networks=35.187.238.122/32,49.36.121.112/32 \
  --project=mosaic-clinical-trials
```

Allows specific IP addresses to connect to Cloud SQL over TCP. `/32` means exactly that one IP address. Pass multiple IPs comma-separated. **Always include ALL IPs you want whitelisted** — this command REPLACES the entire list, not appends to it.

---

#### Check instance status

bash

```bash
gcloud sql instances describe clinical-trial-db \
  --project=mosaic-clinical-trials \
  --format="value(state)"
```

Returns the current state: `RUNNABLE`, `STOPPED`, `MAINTENANCE`, or `PENDING_CREATE`. Always check this before trying to connect — connections fail if state is not `RUNNABLE`.

---

#### Get the instance IP address

bash

```bash
gcloud sql instances describe clinical-trial-db \
  --project=mosaic-clinical-trials \
  --format="value(ipAddresses[0].ipAddress)"
```

Returns just the public IP address. We put this in `.env` as `DB_HOST`.

---

#### Start the instance

bash

```bash
gcloud sql instances patch clinical-trial-db \
  --activation-policy=ALWAYS \
  --project=mosaic-clinical-trials
```

Starts a stopped instance. `ALWAYS` means run continuously. Takes 1-3 minutes to go from STOPPED to RUNNABLE.

---

#### Stop the instance to save cost

bash

```bash
gcloud sql instances patch clinical-trial-db \
  --activation-policy=NEVER \
  --project=mosaic-clinical-trials
```

Stops the instance. You only pay for storage (~$0.50/month) when stopped. Data is fully preserved. Run this after every recording session.

---

#### List all users

bash

```bash
gcloud sql users list \
  --instance=clinical-trial-db \
  --project=mosaic-clinical-trials
```

Shows all database users. We used this when we forgot the username.

---

#### Connect via psql

bash

```bash
psql "host=34.133.55.17 port=5432 dbname=clinical_trial_db user=mosaic_user"
```

Opens a direct PostgreSQL connection. Used to create schema, run queries, verify tables. Requires your IP to be whitelisted first.

---

### Part 5 — Cloud Storage Commands

#### Create a bucket

bash

```bash
gsutil mb -p mosaic-clinical-trials -l us-central1 gs://mosaic-clinical-trials-bucket-001
```

* `gsutil mb` — make bucket
* `-p mosaic-clinical-trials` — which project
* `-l us-central1` — which region
* `gs://...` — the bucket name with the `gs://` prefix

---

#### List bucket contents

bash

```bash
gsutil ls gs://mosaic-clinical-trials-bucket-001
```

Shows top-level folders in the bucket.

---

#### List files in a specific folder

bash

```bash
gsutil ls gs://mosaic-clinical-trials-bucket-001/processed/studies/
```

Shows all processed study files.

---

#### Count files in bucket

bash

```bash
gsutil ls gs://mosaic-clinical-trials-bucket-001/processed/studies/ |wc -l
```

`wc -l` counts the lines of output — giving us the total file count.

---

### Part 6 — Secret Manager Commands

#### Create a secret

bash

```bash
echo -n "YOUR_SECRET_VALUE"| gcloud secrets create openai-api-key \
  --data-file=- \
  --replication-policy=automatic \
  --project=mosaic-clinical-trials
```

* `echo -n` — prints the value without a trailing newline (`-n` = no newline). Important — a trailing newline would become part of the secret value
* `--data-file=-` — read secret value from stdin (the piped echo output)
* `--replication-policy=automatic` — GCP decides where to store it

---

#### Update an existing secret

bash

```bash
echo -n "NEW_VALUE"| gcloud secrets versions add openai-api-key \
  --data-file=- \
  --project=mosaic-clinical-trials
```

Adds a new version of the secret. Cloud Run always reads `:latest` which points to the newest version.

---

#### List all secrets

bash

```bash
gcloud secrets list --project=mosaic-clinical-trials
```

Shows all secrets in the project. We used this to confirm all three secrets were created before deploying.

---

### Part 7 — IAM and Service Account Commands

#### Create a service account

bash

```bash
gcloud iam service-accounts create mosaic-sa \
  --display-name="MOSAIC API Service Account"\
  --project=mosaic-clinical-trials
```

Creates an identity for Cloud Run to use. Service accounts are like user accounts but for applications — not humans.

---

#### Grant Cloud SQL access

bash

```bash
gcloud projects add-iam-policy-binding mosaic-clinical-trials \
  --member="serviceAccount:mosaic-sa@mosaic-clinical-trials.iam.gserviceaccount.com"\
  --role="roles/cloudsql.client"
```

---

#### Grant Cloud Storage access

bash

```bash
gcloud projects add-iam-policy-binding mosaic-clinical-trials \
  --member="serviceAccount:mosaic-sa@mosaic-clinical-trials.iam.gserviceaccount.com"\
  --role="roles/storage.objectAdmin"
```

---

#### Grant Secret Manager access

bash

```bash
gcloud projects add-iam-policy-binding mosaic-clinical-trials \
  --member="serviceAccount:mosaic-sa@mosaic-clinical-trials.iam.gserviceaccount.com"\
  --role="roles/secretmanager.secretAccessor"
```

**Why three separate grant commands?**

GCP follows the principle of least privilege — you grant only the minimum permissions needed. One role per service, not one "admin everything" role. If the service account is ever compromised, the attacker can only access what was explicitly granted.

---

### Part 8 — Cloud Run Commands

#### Deploy the service

bash

```bash
gcloud run deploy mosaic-api \
  --image=gcr.io/mosaic-clinical-trials/mosaic-api:latest \
  --platform=managed \
  --region=us-central1 \
  --service-account=mosaic-sa@mosaic-clinical-trials.iam.gserviceaccount.com \
  --add-cloudsql-instances=mosaic-clinical-trials:us-central1:clinical-trial-db \
  --set-env-vars="..."\
  --set-secrets="OPENAI_API_KEY=openai-api-key:latest,DB_PASSWORD=db-password:latest"\
  --port=8000\
  --min-instances=0\
  --max-instances=3\
  --memory=2Gi \
  --cpu=2\
  --timeout=300\
  --concurrency=1\
  --no-allow-unauthenticated \
  --project=mosaic-clinical-trials
```

Full deployment command — covered in detail earlier in this session.

---

#### Get the service URL

bash

```bash
gcloud run services describe mosaic-api \
  --platform=managed \
  --region=us-central1 \
  --project=mosaic-clinical-trials \
  --format="value(status.url)"
```

---

#### Get an identity token for API calls

bash

```bash
gcloud auth print-identity-token
```

Generates a short-lived token valid for ~1 hour. Used in the `Authorization: Bearer` header for authenticated API calls. We embed it directly in curl commands with `$(gcloud auth print-identity-token)` so it regenerates automatically.

---

#### View Cloud Run logs

bash

```bash
gcloud logging read\
"resource.type=cloud_run_revision AND resource.labels.service_name=mosaic-api"\
  --limit=50\
  --format="value(textPayload)"\
  --project=mosaic-clinical-trials
```

Reads the last 50 log lines from the terminal. Faster than opening the browser for quick debugging.

---

#### Health check via curl

bash

```bash
curl -s \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"\
  https://mosaic-api-569957100480.us-central1.run.app/api/v1/health | python3 -m json.tool
```

---

#### Run analysis via curl

bash

```bash
curl -s \
  -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"\
  -H "Content-Type: application/json"\
  -d '{"task": "Find completed clinical trials where results were never posted"}'\
  https://mosaic-api-569957100480.us-central1.run.app/api/v1/analyze | python3 -m json.tool
```

---

### Quick Reference Card

```
START SESSION:
  gcloud config set project mosaic-clinical-trials
  gcloud sql instances patch clinical-trial-db --activation-policy=ALWAYS --project=mosaic-clinical-trials
  gcloud auth application-default login

END SESSION:
  gcloud sql instances patch clinical-trial-db --activation-policy=NEVER --project=mosaic-clinical-trials

REDEPLOY AFTER CODE CHANGE:
  docker buildx build --platform linux/amd64 --tag gcr.io/mosaic-clinical-trials/mosaic-api:latest --file deployment/Dockerfile --push .
  gcloud run deploy mosaic-api --image=gcr.io/mosaic-clinical-trials/mosaic-api:latest --region=us-central1 --project=mosaic-clinical-trials

CHECK HEALTH:
  curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" https://mosaic-api-569957100480.us-central1.run.app/api/v1/health | python3 -m json.tool

RUN ANALYSIS:
  curl -s -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" -H "Content-Type: application/json" -d '{"task": "Find completed trials with missing results"}' https://mosaic-api-569957100480.us-central1.run.app/api/v1/analyze | python3 -m json.tool
```

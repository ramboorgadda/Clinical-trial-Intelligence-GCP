project name: clinical-trail-intelligence
gcloud auth login
confirm that our python can see GCP

gcloud auth application-default login

get the project value

gcloud config get-value project

Confirms which project is currently active.

export CLOUDSDK_CORE_PROJECT=PROJECT_ID

creating GCS Bucket
gcloud storage buckets create gs://clinical-trials-bucket-010 --project=clinical-trail-intelligence --location=us-central1

creating Cloud SQL Instance
gcloud sql instances create clinical-trial-db --database-version=POSTGRES_15 --tier=db-f1-micro --region=us-central1 --project=clinical-trail-intelligence

Check the status

gcloud sql instances list --project=clinical-trail-intelligence

Deletes an Instance
gcloud sql instances delete clinical-trial-db --project=PROJECT_ID

Create the database

gcloud sql databases create clinical_trial_db \
  --instance=clinical-trial-db \
  --project=clinical-trail-intelligence

Create Database inside the instance
gcloud sql users create mosaic_user --instance=clinical-trial-db --password=mosaic_pass_2024 --project=clinical-trail-intelligence



curl.exe -4 ifconfig.me

69.250.234.102

gcloud sql instances patch clinical-trial-db --authorized-networks=69.250.234.102/32 --project=clinical-trail-intelligence

Connect to the DB

psql -h 34.60.239.203 -p 5432 -U mosaic_user -d clinical_trial_db
Above command will prompt to usr and password



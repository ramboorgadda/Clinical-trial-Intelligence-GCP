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
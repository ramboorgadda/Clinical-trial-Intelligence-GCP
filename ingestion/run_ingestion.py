# It is going to run entire ingestion pipeline
# run this file to fetch studies, fetch papers and parse everything.
# save it to the google cloud storage.

# fetch studies from clinicaltrials.gov
# save the raw studies to GCS
# parse the raw studies into clean structured records
# save the parsed studies to GCS

# for each research study, fetch the related research papers 
# save the raw and parsed papers to GCS
# save and load the documents to and from GCS
# This is permanent storage for the documents and their metadata.
# saves the raw APi responses to GCS bucket as JSON
# saves parsed study and paper records to GCS and JSON
# loan the documents back from GCS for agent use and analysis
# list available documents by prefix - useful for batch processing

# why we save the raw data first ?
# If the parser has a bug, raw originals are safe in GCS
# folder structure can you expect in GCS
# raw/studies/NCT082341.json --> exactly what the API returned for a study
# raw/papers/PMC123456.json --> exactly what the pubMed API returned for a paper
# processed/studies/NCT082341.json --> cleaned and normalized study record
# processed/papers/PMC123456.json --> cleaned and normalized paper record
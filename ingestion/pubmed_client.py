# fetch the research papares from pubMed that reference specific
# clinical trials and their interventions and conditions.This is our 2nd data source for the agent. It is connected to the PubMed API and fetches
# what is does:
# Takes an NCT ID (e.g. NCT082341) and fetches the research papers that reference this clinical trial.
# Fetches the full abstract and metadata for each paper.
# returns paw paper records - no cleaning happens here.


# clinicaltrails.gov tells what study was promised to measure
# pubMed tells what researchers actually published.
# Gap between those things is where the signals live.

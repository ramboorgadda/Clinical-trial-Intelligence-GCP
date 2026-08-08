##############################################################################
# ingestion/clinical_trials_client.py
#
# PURPOSE:
#   This is the first file that talks to the outside world.
#   It connects to ClinicalTrials.gov — a free US government database
#   that stores every registered medical research study.
#   It downloads study records and returns them as Python dictionaries.
#
# WHAT IT DOES STEP BY STEP:
#   1. Opens a connection to the ClinicalTrials.gov API
#   2. Searches for studies by condition, sponsor, or intervention
#   3. Handles pagination — the API returns 100 studies at a time
#      so we keep asking for the next page until we have enough
#   4. Handles failures — if the API is slow or drops the connection,
#      we automatically retry instead of crashing
#   5. Returns raw study data exactly as the API gave it to us
#      We never modify the data here — that is document_parser.py's job
#
# IMPORTANT DESIGN DECISION — WHY requests AND NOT httpx:
#   Most modern async Python code uses httpx for HTTP calls.
#   We tried httpx first — ClinicalTrials.gov returned 403 Forbidden.
#   The reason: ClinicalTrials.gov uses bot protection that checks
#   the TLS fingerprint of the HTTP client. httpx has a different
#   fingerprint from a real browser. requests matches closely enough.
#   This is a real production debugging decision — not a textbook choice.
#   We wrap requests inside asyncio.to_thread() to keep it async.
#
# SHOULD YOU RUN THIS FILE DIRECTLY?
#   No — do not run this file directly.
#   This file is a CLIENT — it provides a class that other files use.
#   You run run_ingestion.py which imports and uses this client.
#   Think of this file like a car engine — you do not start the engine
#   directly, you turn the ignition key (run_ingestion.py).
#
# HOW OTHER FILES USE THIS:
#   from ingestion.clinical_trials_client import ClinicalTrialsClient
#
#   async with ClinicalTrialsClient() as client:
#       studies = await client.search_studies(
#           condition="diabetes",
#           max_results=50
#       )
##############################################################################

import asyncio
import requests
from typing import Any
from tenacity import(
    retry, 
    stop_after_attempt, 
    wait_exponential, 
    retry_if_exception_type
)
from config import settings
from config.settings import settings
from config.logging_config import setup_logging

logger = setup_logging(__name__)

BASE_URL = settings.clinical_trials_base_url

PAGE_SIZE = settings.clinical_trials_page_size

REQUEST_TIMEOUT = 30  # seconds

MAX_RETRIES = 3

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
}

# ─────────────────────────────────────────────────────────────
# CLIENT CLASS
#
# A class is a blueprint for creating objects.
# ClinicalTrialsClient is a blueprint for an object that knows
# how to talk to the ClinicalTrials.gov API.
#
# We designed it as an "async context manager" — meaning you
# use it with the "async with" keyword:
#
#   async with ClinicalTrialsClient() as client:
#       studies = await client.search_studies(condition="diabetes")
#
# The "async with" pattern guarantees that the HTTP session
# is properly opened before use and properly closed after —
# even if an error occurs in the middle.
# ─────────────────────────────────────────────────────────────


class ClinicalTrialsClient:
    """
    A client for downloading study records from ClinicalTrials.gov.

    This client handles everything needed to talk to the API:
    - Opening and closing the HTTP session
    - Building the correct URL and parameters for each request
    - Handling pagination (the API gives 100 results at a time)
    - Retrying automatically when the network fails

    Always use it with "async with" to ensure proper cleanup:

        async with ClinicalTrialsClient() as client:
            studies = await client.search_studies(condition="cancer")
    """
    
    def __init__(self):
        self._session: requests.Session | None = None
        
    async def __aenter__(self) -> "ClinicalTrialsClient":
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        logger.info("Clinical Trials client is opened")
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            self._session.close()
            logger.info("Clinical Trials client is closed")
            
    # ── CORE METHOD: SEARCH STUDIES ───────────────────────────
    
    async def search_studies(self,
        condition: str | None = None,
        intervention: str | None = None,
        sponsor: str | None = None,
        status: list[str] | None = None,
        max_results: int = 100
    ) -> list[dict[str, Any]]:
        # Implementation goes here
        all_studies: list[dict[str, Any]] = []
        
        next_page_token: str | None = None
        
        page_number = 0
        logger.info(
            f"searching studies | "
            f"condition={condition}, "
            f"intervention={intervention}, "
            f"sponsor={sponsor}, "
            f"status={status}, "
            f"max_results={max_results}"
        )
        while len(all_studies) < max_results:
            
            page_number +=1
             
        return all_studies
     
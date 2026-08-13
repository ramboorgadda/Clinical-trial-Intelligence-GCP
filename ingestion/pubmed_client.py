##############################################################################
# ingestion/pubmed_client.py
#
# PURPOSE:
#   This file talks to PubMed — a free database run by the US government
#   that stores millions of published medical research papers.
#   It finds and downloads research papers that reference specific
#   clinical trials from ClinicalTrials.gov.
#
# WHY WE NEED THIS:
#   ClinicalTrials.gov tells us what a study PROMISED to measure.
#   PubMed tells us what researchers ACTUALLY PUBLISHED about it.
#   The gap between those two things is where signals live.
#   Example: A trial files "no serious side effects observed"
#            but three published papers discuss concerning safety events.
#            That gap is a signal worth flagging.
#
# HOW PUBMED SEARCH WORKS — TWO STEPS:
#   PubMed does not let you search and get full details in one call.
#   It requires two separate API calls:
#
#   Step 1 — esearch:
#     Send a search query → get back a list of paper IDs
#     Example: search for "NCT04788680" → get back ["38234567", "37891234"]
#
#   Step 2 — efetch:
#     Send those paper IDs → get back full paper details
#     Example: send ["38234567", "37891234"] → get title, abstract, authors
#
#   This two-step design is how PubMed's eUtils API works.
#   We cannot skip step 1 and jump straight to step 2.
#
# RATE LIMITING — IMPORTANT:
#   PubMed allows 3 requests per second without an API key.
#   If we send requests faster than that, they get blocked.
#   We add a 400ms sleep between requests to stay safely under the limit.
#   400ms = 2.5 requests per second — safely below the 3/second limit.
#
# SHOULD YOU RUN THIS FILE DIRECTLY?
#   No — same as clinical_trials_client.py, this is a client class.
#   It gets imported and used by run_ingestion.py.
#   Do not run it directly.
#
# HOW OTHER FILES USE THIS:
#   from ingestion.pubmed_client import PubMedClient
#
#   async with PubMedClient() as client:
#       papers = await client.fetch_papers_for_trial("NCT04788680")
##############################################################################

import asyncio
import httpx
from typing import Any
from tenacity import( retry, 
                    stop_after_attempt, 
                    wait_exponential,
                    retry_if_exception_type)
from config.settings import settings
from config.logging_config import setup_logger
logger = setup_logger(__name__)

# Constants

BASE_URL = settings.PUBMED_BASE_URL
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
FETCH_BATCH_SIZE = 20 # Number of paper IDs to fetch in one efetch request

RATE_LIMIT_SLEEP = 0.4  # 400ms sleep between requests to stay under PubMed's rate limit


class PubMedClient:
    """
    A client for downloading research papers from PubMed.

    Works in two steps for every search:
    1. esearch — find paper IDs matching our query
    2. efetch  — get full details for those paper IDs

    Always use with "async with" for proper connection management:

        async with PubMedClient() as client:
            papers = await client.fetch_papers_for_trial("NCT04788680")
    """
    
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            headers={"Accept": "application/json"},
        )
        logger.info("PubMed client opened")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
            logger.info("PubMed client closed")
            
# Core methods to fetch papers from one trail
    async def fetch_papers_for_trial(
        self, 
        nct_id: str,
        max_results: int = 50,
        
    ) -> list[dict[str, Any]]:
        """
        Fetches all PubMed papers that reference a specific clinical trial.

        Handles the two-step process internally:
        Step 1: esearch — find paper IDs for this NCT ID
        Step 2: efetch  — get full details for those paper IDs

        Args:
            nct_id:      The clinical trial ID to search for.
            max_results: Maximum papers to return.

        Returns:
            List of paper dictionaries with title, abstract, authors etc.
            Empty list if no papers found or request failed.
        """
        logger.info(f"Fetching pubMed papers | nct_id={nct_id} | max_results={max_results}")
        paper_ids = await self._search_paper_ids(nct_id,
                                    max_results=max_results)
        if not paper_ids:
            logger.info(f"No papers found for nct_id={nct_id}")
            return []
        papers = await self._fetch_papers(paper_ids)
        logger.info(
            f"PubMed fetch complete | "
            f"nct_id={nct_id} | "
            f"papers_returned={len(papers)}"
        )
        return papers
    # Core Method to fetch papers for multiple trails
    async def fetch_papers_for_trials(
        self, 
        nct_ids: list[str],
        max_per_trial: int = 20,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Fetches PubMed papers for multiple clinical trials.

        Args:
            nct_ids: List of clinical trial IDs to search for.
            max_per_trial: Maximum papers to return per trial.

        Returns:
            Dictionary mapping each NCT ID to its list of paper dictionaries.
            Example: {"NCT04788680": [paper1, paper2], "NCT01234567": []}
        """
        results: dict[str, list[dict[str, Any]]] = {}
        for i, nct_id in enumerate(nct_ids):
            papers = await self.fetch_papers_for_trial(nct_id, max_results=max_per_trial)
            results[nct_id] = papers
        return results



##############################################################################
# ingestion/gcs_store.py
#
# PURPOSE:
#   This file saves our data to Google Cloud Storage (GCS) — and
#   loads it back when we need it.
#   Think of GCS as a giant hard drive in the cloud that never
#   runs out of space and is always online.
#
# WHY DO WE SAVE TO GCS AT ALL — WHY NOT JUST KEEP DATA IN MEMORY:
#   If our Python program crashes halfway through downloading
#   144 studies, we lose everything if we only kept it in memory.
#   By saving to GCS as we go, even if something crashes,
#   the studies we already downloaded are safe.
#
# THE "RAW vs PROCESSED" PATTERN — WHY WE SAVE DATA TWICE:
#   We save EVERY piece of data in two different forms:
#
#   1. RAW   — exactly what the API gave us, completely untouched.
#              Think of this as a photocopy of the original document.
#   2. PROCESSED — the cleaned-up version after document_parser.py
#              has done its work. Think of this as a neatly typed-up
#              summary of that document.
#
#   WHY BOTH? If our parser (document_parser.py) has a bug and
#   cleans the data incorrectly, we have NOT lost anything —
#   the raw original is still sitting safely in GCS. We can simply
#   fix the parser and re-process the raw data again.
#   This is a real production safety pattern — never throw away
#   your original source data.
#
# THE FOLDER STRUCTURE INSIDE OUR BUCKET:
#   raw/studies/NCT04788680.json        ← exactly what ClinicalTrials.gov sent us
#   raw/papers/38234567.json            ← exactly what PubMed sent us
#   processed/studies/NCT04788680.json  ← the cleaned ParsedStudy object
#   processed/papers/38234567.json      ← the cleaned ParsedPaper object
#
# SHOULD YOU RUN THIS FILE DIRECTLY?
#   No. This file defines a class that run_ingestion.py uses.
#   Do not run it by itself.
#
# HOW OTHER FILES USE THIS:
#   from ingestion.gcs_store import GCSStore
#
#   store = GCSStore()
#   await store.save_raw_study(nct_id="NCT04788680", data=raw_dict)
#   await store.save_parsed_study(study=parsed_study_object)
##############################################################################
import json

from config.logging_config import setup_logging

from config.settings import settings
import asyncio
from typing import Any
from google.cloud import storage
from ingestion.document_parser import ParsedStudy, ParsedPaper
logger = setup_logging(__name__)
# __name__ here = "ingestion.gcs_store"
# ─────────────────────────────────────────────────────────────
# FOLDER PATHS INSIDE OUR BUCKET
#
# A GCS "bucket" does not really have folders the way your
# computer does — but it LOOKS like it has folders because
# every file we save has a path-like name with slashes in it.
# Example: "raw/studies/NCT04788680.json" looks like a folder
# structure even though GCS technically just sees one long name.
# Defining these as constants means if we ever want to change
# the folder layout, we only change it in ONE place.
# ─────────────────────────────────────────────────────────────

PREFIX_RAW_STUDIES = "raw/studies/"
PREFIX_RAW_PAPERS = "raw/papers/"
PREFIX_PROCESSED_STUDIES = "processed/studies/"
PREFIX_PROCESSED_PAPERS = "processed/papers/"

# ─────────────────────────────────────────────────────────────
# THE GCS STORE CLASS
# ─────────────────────────────────────────────────────────────


class GCSStore:
    """Handles saving data to and loading data from Google Cloud Storage.

    IMPORTANT — WHY WE USE asyncio.to_thread() THROUGHOUT THIS FILE:

    Google's official storage library is "synchronous" — meaning
    when you ask it to upload a file, your whole program freezes
    and waits until the upload is done before doing anything else.

    But our entire MOSAIC system is built to be "asynchronous" —
    meaning we want our program to be able to do OTHER things
    while waiting for slow operations like uploads to finish.

    asyncio.to_thread() is the bridge between these two worlds.
    It takes a synchronous function (like a GCS upload) and runs
    it in a separate background thread, while letting our main
    program keep working on other tasks in the meantime.
    Think of it like handing a task to an assistant in another
    room, instead of standing there waiting yourself.
    """
    
    def __init__(self):
        self._client = storage.Client(project=settings.gcp_project_id)
        self._bucket = self._client.bucket(settings.gcs_bucket_name)
        logger.info(f"GCSStore initialized | bucket={settings.gcs_bucket_name} |"
                    f"project={settings.gcp_project_id}")
    # Save a raw study
    async def save_raw_study(self, nct_id: str,
                            data: dict[str,Any]) -> str:
        """
        Saves the EXACT, untouched API response for one study.

        Call this the moment you receive data from the API —
        BEFORE any cleaning or parsing happens. This way, even
        if the parser has a bug, the original is always safe.

        Args:
            nct_id: The study's ID, used as the filename.
            data:   The raw study dictionary to save.

        Returns:
            The path inside GCS where the file was saved.
            Example: "raw/studies/NCT04788680.json"
        """
        gcs_path = f"{PREFIX_RAW_STUDIES}{nct_id}.json"
        
        await self._upload_json(path=gcs_path, data=data)
        return gcs_path
    # ── SAVE A RAW PAPER ───────────────────────────────────────
    async def save_raw_paper(self,pmid: str, data: dict[str,Any]) -> str:
        """
        Saves the EXACT, untouched API response for one paper.

        Call this the moment you receive data from the API —
        BEFORE any cleaning or parsing happens. This way, even
        if the parser has a bug, the original is always safe.

        Args:
            pmid: The paper's PubMed ID, used as the filename.
            data: The raw paper dictionary to save.
        """
        gcs_path = f"{PREFIX_RAW_PAPERS}{pmid}.json"
        await self._upload_json(path=gcs_path, data=data)
        return gcs_path
    # Save a clean parsed study
    async def save_parsed_study(self, study: ParsedStudy) -> str:
        """
        Saves a clean, parsed study object to GCS.

        This is the version of the study after document_parser.py
        has cleaned and structured it. If you ever need to re-run
        the parser, you can always go back to the raw version.

        Args:
            study: The ParsedStudy object to save.

        Returns:
            The path inside GCS where the file was saved.
            Example: "processed/studies/NCT04788680.json"
        """
        gcs_path = f"{PREFIX_PROCESSED_STUDIES}{study.nct_id}.json"
        await self._upload_json(path=gcs_path, data=study.model_dump())
        logger.info(
            f"Saved parsed study | nct_id={study.nct_id} | path={gcs_path}"
        )
        return gcs_path
    async def save_parsed_paper(self, paper: ParsedPaper) -> str:
        """
        Saves a clean, parsed paper object to GCS.

        This is the version of the paper after document_parser.py
        has cleaned and structured it. If you ever need to re-run
        the parser, you can always go back to the raw version.

        Args:
            paper: The ParsedPaper object to save.

        Returns:
            The path inside GCS where the file was saved.
            Example: "processed/papers/12345678.json"
        """
        gcs_path = f"{PREFIX_PROCESSED_PAPERS}{paper.pmid}.json"
        await self._upload_json(path=gcs_path, data=paper.model_dump())
        logger.info(
            f"Saved parsed paper | pmid={paper.pmid} | path={gcs_path}"
        )
        return gcs_path
    async def load_parsed_study(self,nct_id: str) -> ParsedStudy | None:
        """
        Loads a previously saved, cleaned study back from GCS.

        This is the REVERSE of save_parsed_study — we use this
        in the processing layer when we need to read studies
        back in to chunk and embed them.

        Args:
            nct_id: Which study to load, by its NCT ID.

        Returns:
            A ParsedStudy object if found.
            None if no study with that ID exists in GCS.
        """
        gcs_path = f"{PREFIX_PROCESSED_STUDIES}{nct_id}.json"
        data = await self._download_json(path=gcs_path)
        # Download the raw JSON text and convert it back to a
        # Python dictionary (our private helper does this).
        if data is None:
            return None
        return ParsedStudy(**data)
         # **data "unpacks" the dictionary into keyword arguments.
        # Example: if data = {"nct_id": "NCT123", "title": "..."}
        # then ParsedStudy(**data) is the same as writing:
        # ParsedStudy(nct_id="NCT123", title="...")
        # This rebuilds our typed Pydantic object from the saved dict.
    async def list_processed_studies(self) -> list[str]:
        """
        Lists all the NCT IDs of studies that have been saved in GCS.

        This is useful for knowing which studies have already been
        processed and saved, so we don't re-download or re-process
        them unnecessarily.

        Returns:
            A list of NCT IDs (strings) for all processed studies.
        """
        prefix = PREFIX_PROCESSED_STUDIES
        blobs = self._bucket.list_blobs(prefix=prefix)
        nct_ids = []
        async for blob in blobs:
            # Each blob's name looks like "processed/studies/NCT12345678.json"
            # We want to extract just the NCT ID part.
            name = blob.name
            if name.endswith(".json"):
                nct_id = name[len(prefix):-len(".json")]
                nct_ids.append(nct_id)
        logger.info(f"Listed processed studies | count={len(nct_ids)}")
        return nct_ids
        # ── PRIVATE HELPER: UPLOAD ANY DICT AS A JSON FILE ────────
    async def _upload_json(self, path: str, data: dict[str, Any]) -> None:
        """
        Uploads a Python dictionary as a JSON file to GCS.

        Args:
            path: The path in GCS where the JSON should be saved.
            data: The dictionary to upload.
        """
        json_bytes = json.dumps(data, indent=2,default = str).encode("utf-8")  # Convert dict to pretty-printed JSON string
        blob = self._bucket.blob(path)
        await asyncio.to_thread(blob.upload_from_string, json_bytes, content_type="application/json")
        
    async def _download_json(
        self,
        path: str,
    ) -> dict[str, Any] | None:
        """
        The shared internal method that downloads a file from GCS
        and converts it back into a Python dictionary.

        Args:
            path: The path inside the GCS bucket to download from.

        Returns:
            A Python dictionary if the file was found.
            None if the file does not exist or something went wrong.
        """

        try:
            blob = self._bucket.blob(path)
            # Point to the file we want to download.

            json_bytes = await asyncio.to_thread(blob.download_as_bytes)
            # Download the file's raw content as bytes.
            # Again wrapped in asyncio.to_thread() since this
            # Google library call is synchronous by default.

            return json.loads(json_bytes.decode("utf-8"))
            # Step 1: .decode("utf-8") turns the raw bytes back
            #         into readable text.
            # Step 2: json.loads(...) turns that JSON text back
            #         into a Python dictionary we can work with.

        except Exception as e:
            if "404" in str(e) or "Not Found" in str(e):
                # A 404 simply means "this file does not exist".
                # This is an EXPECTED situation sometimes — not a bug.
                logger.warning(f"File not found in GCS | path={path}")
            else:
                # Anything else is a real, unexpected problem —
                # log it as an error so we can investigate.
                logger.error(
                    f"Failed to download from GCS | path={path} | error={e}"
                )
            return None
##############################################################################
# processing/run_processing.py
#
# PURPOSE:
#   This is the entry point for the PROCESSING pipeline.
#   It is the second major pipeline you run after run_ingestion.py.
#
# WHAT IT DOES IN ORDER:
#   1. Reads all cleaned study files from Google Cloud Storage
#   2. Saves each study's metadata into the Cloud SQL studies table
#      (required first because chunks have a foreign key to studies)
#   3. Splits each study's text into overlapping chunks (chunker.py)
#   4. Converts each chunk into 1536 numbers via OpenAI (embedder.py)
#   5. Saves chunks + embeddings into Cloud SQL chunks table (vector_store.py)
#
# WHY THIS ORDER MATTERS:
#   chunks table has: nct_id REFERENCES studies(nct_id)
#   This is a foreign key constraint — it means we CANNOT save a chunk
#   for a study that does not yet exist in the studies table.
#   So we ALWAYS save study metadata to Cloud SQL BEFORE saving chunks.
#   Getting this order wrong causes ForeignKeyViolationError on every insert.
#
# SHOULD YOU RUN THIS FILE DIRECTLY?
#   YES — this is the second file you run directly after run_ingestion.py
#
#   Make sure your .venv is active and .env is filled in, then:
#   python3 processing/run_processing.py
#
# WHAT OUTPUT TO EXPECT:
#   2024-03-15 14:32:11 | INFO | Starting MOSAIC processing pipeline
#   2024-03-15 14:32:11 | INFO | Found 150 studies in GCS
#   2024-03-15 14:32:15 | INFO | Loaded 150 studies successfully
#   2024-03-15 14:32:15 | INFO | Inserted 150 studies into database
#   2024-03-15 14:32:16 | INFO | Chunked all studies | total_chunks=312
#   2024-03-15 14:32:16 | INFO | Starting embedding | total_chunks=312
#   2024-03-15 14:32:18 | INFO | Embedding batch 1/7 | chunks_in_batch=50
#   2024-03-15 14:32:20 | INFO | Batch embedded successfully | chunks=50 | embedding_dims=1536
#   ... repeats for each batch ...
#   2024-03-15 14:32:45 | INFO | Chunks saved | saved=312 | skipped=0
#   2024-03-15 14:32:45 | INFO | Processing complete
#   2024-03-15 14:32:45 | INFO | Studies processed : 150
#   2024-03-15 14:32:45 | INFO | Chunks created    : 312
#   2024-03-15 14:32:45 | INFO | Chunks embedded   : 312
#   2024-03-15 14:32:45 | INFO | Chunks stored     : 312
##############################################################################
import asyncio
from ingestion.document_parser import ParsedStudy
from ingestion.gcs_store import GCSStore
from processing.chunker import Chunker
from processing.embedder import Embedder
from processing.vector_store import VectorStore
from config.logging_config import setup_logging
logger = setup_logging(__name__)


async def run_processing():
    """Runs the complete processing pipeline from start to finish.

    Reads cleaned studies from GCS, chunks them, embeds them via
    OpenAI, and stores everything in Cloud SQL for agent search.
    """
    logger.info("Starting MOSAIC processing pipeline")
    gcs_store = GCSStore()
    chunker = Chunker()
    embedder = Embedder()
    vector_store = VectorStore()
    logger.info("Loading parsed studies from GCS...")
    nct_ids =await gcs_store.list_processed_studies()
    logger.info(f"Found {len(nct_ids)} studies in GCS")
    
    studies: list[ParsedStudy] = []
    for nct_id in nct_ids:
        study = await gcs_store.load_parsed_study(nct_id)
        if study is not None:
            studies.append(study)
        logger.info(f"Loaded {len(studies)} studies successfully")
    # ── OPEN THE DATABASE CONNECTION ───────────────────────────
    async with VectorStore() as vector_store:
        # "async with" opens the connection pool when we enter
        # and GUARANTEES it closes when we exit — even if an
        # error occurs halfway through. This is the correct way
        # to use VectorStore — never open it manually.

        # ── STEP 2: SAVE STUDY METADATA TO CLOUD SQL ──────────
        # IMPORTANT: We MUST do this BEFORE saving chunks.
        # The chunks table has a foreign key to the studies table.
        # If we try to save chunks first, every insert will fail
        # with ForeignKeyViolationError because the studies do
        # not exist in the database yet.
        logger.info("Saving study metadata to Cloud SQL...")
        for study in studies:
            success = await vector_store.save_Study(
                study_data = {
                    "nct_id": study.nct_id,
                    "title": study.title,
                    "description": study.description,
                    "status": study.status,
                    "start_date": study.start_date,
                    "completion_date": study.completion_date,
                    "phase": study.phase,
                    "sponsor": study.sponsor,
                    "conditions": study.conditions,
                    "interventions": study.interventions,
                    "locations": study.locations,
                    "results_posted": study.results_posted,
                    "enrollment": study.enrollment,
                    "gcs_path": f"processed/studies/{study.nct_id}.json",
                }
            )
            if success:
                    studies_saved += 1
        
        logger.info(f"Study metadata saved successfully: {studies_saved} studies") 
##############################################################################
# processing/vector_store.py
#
# PURPOSE:
#   This file saves EmbeddedChunks into Cloud SQL's chunks table
#   and provides semantic search — finding chunks by MEANING
#   rather than by keyword.
#
# THIS IS THE HEART OF THE ENTIRE SYSTEM.
#   Every agent query flows through this file.
#   When the Missing Results agent asks:
#   "find studies where sponsor never posted results"
#   — this file is what finds the answer.
#
# HOW SEMANTIC SEARCH WORKS HERE — STEP BY STEP:
#   1. The agent's question gets converted to 1536 numbers (embedder.py)
#   2. This file sends those 1536 numbers to Cloud SQL
#   3. pgvector compares them against every chunk's 1536 numbers
#   4. The chunks whose numbers are CLOSEST get returned
#   5. "Closest" is measured using cosine similarity — the <=> operator
#
# WHAT IS COSINE SIMILARITY?
#   Imagine two arrows pointing in different directions.
#   Cosine similarity measures the ANGLE between those arrows.
#   A small angle = similar meaning = small cosine distance.
#   A large angle = different meaning = large cosine distance.
#   The <=> operator in pgvector does this calculation for us.
#
# WHY asyncpg AND NOT SQLAlchemy?
#   SQLAlchemy is great for standard queries but pgvector's
#   VECTOR type is not natively supported by SQLAlchemy's ORM.
#   asyncpg is a raw async PostgreSQL driver — it gives us
#   complete control over the SQL we write, which means we
#   can use pgvector's custom operators (<=> for cosine distance)
#   without any compatibility issues.
#
# THE CODEC — THE MOST IMPORTANT TECHNICAL DETAIL:
#   asyncpg does not know what a VECTOR type is by default.
#   PostgreSQL knows, but asyncpg needs to be taught how to
#   convert between Python lists and PostgreSQL VECTOR columns.
#   We register a custom codec — a translator — that handles this.
#   Without it, every insert and select would crash with a type error.
#
# SHOULD YOU RUN THIS FILE DIRECTLY?
#   No. This defines a class used by run_processing.py and the agents.
#
# HOW OTHER FILES USE THIS:
#   from processing.vector_store import VectorStore
#
#   vs = VectorStore()
#   await vs.init()
#   await vs.save_embedded_chunks(list_of_embedded_chunks)
#   results = await vs.search(query_embedding, top_k=5)
##############################################################################
import asyncio
import asyncpg
import json
from typing import Any
from processing.embedder import EmbeddedChunk
from config.settings import settings
from config.logging_config import setup_logging
logger = setup_logging(__name__)
# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

POOL_MIN_SIZE = 2
# Minimum number of database connections to keep open at all times.
# Think of a connection pool like a team of workers —
# we always keep at least 2 ready to handle requests immediately.

POOL_MAX_SIZE = 10
# Maximum number of connections allowed at the same time.
# More connections = more parallelism but more DB memory usage.
# 10 is a safe ceiling for our db-f1-micro Cloud SQL instance.

TOP_K_DEFAULT = 5
# Default number of similar chunks to return per search query.
# When an agent searches, it gets back the 5 most relevant chunks
# by default. Agents can override this if they need more.


# ─────────────────────────────────────────────────────────────
# THE VECTOR STORE CLASS
# ─────────────────────────────────────────────────────────────

class VectorStore:
    """
    Saves EmbeddedChunks to Cloud SQL and enables semantic search
    over them using pgvector's cosine similarity operator.

    LIFECYCLE — always follow this order:
        vs = VectorStore()   # create
        await vs.init()      # connect to database
        # ... use it ...
        await vs.close()     # disconnect cleanly

    OR use it as an async context manager:
        async with VectorStore() as vs:
            await vs.save_embedded_chunks(chunks)
            results = await vs.search(query_embedding)
    """
    def __init__(self):
        self._pool: asyncpg.Pool | None = None
        # The connection pool — our team of database workers.
        # Starts as None — created when init() is called.
        # We never create connections one by one — always use
        # the pool so connections are reused efficiently.
    
    async def __aenter__(self) -> "VectorStore":
        await self.init()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Closes the connection pool when exiting 'async with'."""
        await self.close()
    async def init(self) -> None:
        """
        Creates the asyncpg connection pool and registers the
        pgvector codec so Python can read and write VECTOR columns.

        MUST be called before any other method.
        This is where we actually connect to Cloud SQL.
        """
        logger.info(f"connecting to cloudsql |"
                    f"host = {settings.db_host} |"
                    f"database name = {settings.db_name}")
        self._pool = await asyncpg.create_pool(
            host=settings.db_host,
            port = int(settings.db_port),
            database=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            min_size=POOL_MIN_SIZE,
            max_size=POOL_MAX_SIZE,
            init = self._init_connection
            # This is the KEY parameter — explained in detail below.
            # init= means: "run this function on EVERY new connection
            # the pool creates." We use it to register our pgvector codec.
        )
        logger.info("Connection pool created successfully")

    async def _init_connection(self, conn: asyncpg.Connection) -> None:
        """
        Runs automatically on every new database connection.

        This is where we register the pgvector codec —
        the translator that teaches asyncpg how to convert
        between Python lists and PostgreSQL VECTOR columns.

        WITHOUT THIS:
            Saving a chunk → TypeError: cannot convert list to VECTOR
            Reading a chunk → asyncpg.exceptions.UndefinedTypeError

        WITH THIS:
            Python [0.023, -0.041, 0.891, ...] ↔ PostgreSQL VECTOR(1536)
            The conversion happens automatically, invisibly.

        Args:
            conn: A fresh asyncpg connection, just created by the pool.
        """
        await conn.set_type_codec(
            "vector",
            # The PostgreSQL type name we are teaching asyncpg about.
            # This matches the VECTOR column type in our chunks table.
            encoder=lambda v: json.dumps(v),
            
            # ENCODER: Python → PostgreSQL
            # When we SAVE a chunk, asyncpg needs to convert our
            # Python list [0.023, -0.041, ...] into something
            # PostgreSQL understands.
            # json.dumps([0.023, -0.041]) → "[0.023, -0.041]"
            # PostgreSQL's pgvector accepts this JSON string format.
            decoder=lambda v: json.loads(v),
            # DECODER: PostgreSQL → Python
            # When we READ a chunk back, pgvector returns the
            # vector as a string "[0.023, -0.041, ...]"
            # json.loads converts it back to a Python list.
            schema="public",
            format="text",
            # Use text format for the conversion.
            # "text" means the encoder/decoder work with strings.
            # The alternative is "binary" (raw bytes) — text is
            # simpler and perfectly fast for our use case.
            
        )
        
    async def close(self) -> None:
        """
        Gracefully closes all database connections in the pool.
        Always call this when you are done with the VectorStore.
        Leaving connections open wastes Cloud SQL resources.
        """
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Connection pool closed successfully")
# ── SAVE EMBEDDED CHUNKS TO CLOUD SQL ─────────────────────
    async def save_embedded_chunk(self,
                                chunks: list[EmbeddedChunk]) -> int:
        """
        Saves a list of EmbeddedChunks into the chunks table.

        Uses INSERT ... ON CONFLICT DO NOTHING so it is safe
        to run multiple times — duplicate chunks are silently
        skipped instead of causing an error.

        Args:
            chunks: List of EmbeddedChunk objects to save.

        Returns:
            Number of chunks successfully saved.
        """
        if not chunks:
            logger.warning("save_embedded_chunks called with empty list")
            return 0
        saved_count = 0
        async with self._pool.acquire() as conn:
            # acquire() checks out one connection from the pool.
            # When this block exits, the connection is returned
            # to the pool automatically — not closed, just returned.
            # This is efficient — the next save call reuses it.
            for chunk in chunks:
                try:
                    await conn.execute(
                        """INSERT INTO chunks (nct_id, chunk_text, embedding, chunk_index, source) VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING""",
                        # $1, $2, $3, $4, $5 are parameter placeholders.
                        # asyncpg fills them in from the arguments below.
                        # This is called a parameterised query —
                        # it prevents SQL injection attacks because
                        # the values are never inserted directly into
                        # the SQL string, they are passed separately.
                        #
                        # ON CONFLICT DO NOTHING means:
                        # if a chunk with this chunk_id already exists,
                        # skip it silently instead of raising an error.
                        # This makes the entire processing step idempotent
                        # — safe to run again without duplicating data.
                        chunk.nct_id, 
                        chunk.chunk_text,
                        chunk.embedding, 
                        chunk.chunk_index, 
                        chunk.source
                    )
                    saved_count += 1
                except Exception as e:
                    logger.error(
                        f"Failed to save chunk | "
                        f"chunk_id={chunk.chunk_id} | "
                        f"error={e}"
                    )
                # Here you would execute the SQL insert for each chunk.
                # Example (pseudo-code):
                # await conn.execute(
                #     "INSERT INTO chunks (text, metadata, embedding) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                #     chunk.text, chunk.metadata, chunk.embedding
                # )
        logger.info(
            f"Chunks saved | "
            f"saved={saved_count} | "
            f"total_input={len(chunks)} | "
            f"skipped={len(chunks) - saved_count}"
        )
        return saved_count
    async def save_Study(self, 
                        study_data: dict[str,Any]) -> None:
        """
        Saves one study record into the studies table.

        Uses INSERT ... ON CONFLICT (nct_id) DO UPDATE so that
        if a study already exists, its fields get refreshed
        with the latest data instead of being skipped.

        Args:
            study_data: Dictionary of study fields to save.
        """
        
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO studies
                    (nct_id, title, sponsor, phase, status,
                    conditions, interventions, primary_outcome,
                    secondary_outcomes, start_date, completion_date,
                    results_posted, enrollment, gcs_path)
                    VALUES
                    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    ON CONFLICT (nct_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    sponsor = EXCLUDED.sponsor,
                    phase = EXCLUDED.phase,
                    status = EXCLUDED.status,
                    conditions = EXCLUDED.conditions,
                    interventions = EXCLUDED.interventions,
                    primary_outcome = EXCLUDED.primary_outcome,
                    secondary_outcomes = EXCLUDED.secondary_outcomes,
                    start_date = EXCLUDED.start_date,
                    completion_date = EXCLUDED.completion_date,
                    results_posted = EXCLUDED.results_posted,
                    enrollment = EXCLUDED.enrollment,
                    gcs_path = EXCLUDED.gcs_path
                """,
                study_data.get("nct_id"),
                study_data.get("title"),
                study_data.get("sponsor"),
                study_data.get("phase"),
                study_data.get("status"),
                study_data.get("conditions"),
                study_data.get("interventions"),
                study_data.get("primary_outcome"),
                study_data.get("secondary_outcomes"),
                study_data.get("start_date"),
                study_data.get("completion_date"),
                study_data.get("results_posted"),
                study_data.get("enrollment"),
                study_data.get("gcs_path")
            )
# ── SEMANTIC SEARCH — THE CORE INTELLIGENCE OPERATION ─────
    async def search(self,
                    query_embeddings: list[float],
                    top_k: int = TOP_K_DEFAULT,
                    source_filter: str | None = None,
                    nct_id_filter: str | None = None) -> list[dict[str, Any]]:
        """
        Finds the most semantically similar chunks to a query embedding.

        Uses pgvector's cosine distance operator (<=>)  to compare
        the query embedding against every stored chunk embedding
        and returns the TOP_K closest ones.

        This is the method every agent calls when it needs context.
        It is the bridge between a natural language question and
        the relevant chunks stored in Cloud SQL.

        Args:
            query_embedding:  The search query as 1536 numbers.
            top_k:            How many results to return.
            source_filter:    Optional filter by source type.
            nct_id_filter:    Optional filter by specific study.

        Returns:
            List of dictionaries, each containing:
            - nct_id:      Which study this chunk belongs to
            - chunk_text:  The actual text content
            - chunk_index: Position in the original document
            - source:      "study" or "paper"
            - distance:    Cosine distance (lower = more similar)
            - 0.0 = identical meaning
            - 1.0 = completely different meaning
            - 2.0 = opposite meaning
        """
        conditions = []
        params: list[Any] = [query_embeddings]
        param_count = 1
        # Tracks our parameter numbering ($1, $2, $3...).
        # We increment this each time we add a filter parameter.
        if source_filter is not None:
            conditions.append(f"source = ${param_count}")
            params.append(source_filter)
            param_count += 1
        if nct_id_filter is not None:
            conditions.append(f"nct_id = ${param_count}")
            params.append(nct_id_filter)
            param_count += 1
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
        param_count += 1
        params.append(top_k)
        # top_k is always the last parameter.
        query = f"""
            SELECT
                nct_id,
                chunk_text,
                chunk_index,
                source,
                embedding <=> $1 AS distance
            FROM chunks
            {where_clause}
            ORDER BY distance ASC
            LIMIT ${param_count}
        """
        # This SQL query is the heart of semantic search.
        #
        # embedding <=> $1
        #   The <=> operator is pgvector's cosine distance.
        #   It compares each stored embedding against our query embedding.
        #   Returns a number between 0 and 2.
        #   0 = identical, 1 = orthogonal (unrelated), 2 = opposite.
        #
        # ORDER BY distance ASC
        #   Sort by distance, smallest first.
        #   Smallest distance = most similar meaning = most relevant.
        #
        # LIMIT $N
        #   Return only the top N results.
        #   We do not want all 300 chunks — just the most relevant ones.
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        results = [dict(row) for row in rows]
        logger.info(
            f"Semantic search complete | "
            f"results_found={len(results)} | "
            f"top_k={top_k} | "
            f"source_filter={source_filter} | "
            f"nct_id_filter={nct_id_filter}"
        )

        return results
# Check how many chunks are stored in the database
    async def count_chunks(self) -> int:
        """Returns the total number of chunks currently in the database.
        Used by run_processing.py to report progress after saving.

        Returns:
            Total count of rows in the chunks table.
        """
        async with self._pool.acquire() as conn:
            results = await conn.fetchval("select count(*) from chunks")
        logger.info(f"Total chunks in database: {results}")
        return results
    # ── CHECK IF A STUDY HAS ALREADY BEEN PROCESSED ───────────
    async def is_study_exists(self,nct_id: str) -> bool:
        """Checks if a study with the given NCT ID already exists in the database.

        Args:
            nct_id: The NCT ID of the study to check.

        Returns:
            True if the study exists, False otherwise.
        """
        async with self._pool.acquire() as conn:
            count = await conn.fetchval("select count(*) from chunks where nct_id=$1", nct_id)
        return count > 0
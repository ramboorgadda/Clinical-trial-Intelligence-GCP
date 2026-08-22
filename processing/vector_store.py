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
        if self.pool:
            await self.pool.close()
            logger.info("Connection pool closed successfully")
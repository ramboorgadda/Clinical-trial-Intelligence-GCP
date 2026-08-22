##############################################################################
# processing/embedder.py
#
# PURPOSE:
#   This file takes every TextChunk produced by chunker.py and
#   converts it into a vector embedding — a list of 1536 numbers
#   that mathematically represent the MEANING of that chunk.
#
# WHAT IS A VECTOR EMBEDDING — EXPLAINED SIMPLY:
#   Imagine plotting every word in the English language on a giant
#   map. Words that mean similar things end up close together on
#   that map. "Heart attack" and "myocardial infarction" would be
#   right next to each other even though the words look completely
#   different. "Results never posted" and "no outcomes published"
#   would also be very close together.
#
#   A vector embedding is exactly this — a position on that giant
#   map, expressed as 1536 numbers (coordinates).
#
#   WHY DOES THIS MATTER FOR MOSAIC?
#   When our Missing Results agent asks "find studies where sponsor
#   never posted results", we convert that QUESTION into 1536 numbers
#   too. Then pgvector finds the chunks whose numbers are closest
#   to the question's numbers. That is semantic search —
#   finding by MEANING, not by keyword matching.
#
# WHY text-embedding-3-small AND NOT text-embedding-3-large?
#   text-embedding-3-large produces 3072 dimensions but pgvector's
#   hnsw index has a 2000-dimension hard limit. We discovered this
#   during our build — the index creation failed with a clear error.
#   text-embedding-3-small produces 1536 dimensions — well within
#   the limit, cheaper, faster, and more than sufficient quality
#   for clinical trial signal detection.
#   This is a real production constraint we hit and solved.
#
# BATCHING — WHY WE DON'T EMBED ONE CHUNK AT A TIME:
#   If we sent one API call per chunk, 300 chunks = 300 API calls.
#   That is slow and expensive. OpenAI accepts up to 100 chunks
#   in a single API call. We batch 50 at a time — fast, efficient,
#   and within OpenAI's rate limits comfortably.
#
# SHOULD YOU RUN THIS FILE DIRECTLY?
#   No. This file defines a class used by run_processing.py.
#
# HOW OTHER FILES USE THIS:
#   from processing.embedder import Embedder
#
#   embedder = Embedder()
#   embedded_chunks = await embedder.embed_chunks(list_of_text_chunks)
##############################################################################
import asyncio
from dataclasses import dataclass
from openai import AsyncOpenAI
from processing.chunker import TextChunk
from config.settings import settings
from config.logging_config import setup_logger
logger = setup_logger(__name__)

BATCH_SIZE = 50
# Number of chunks to send in a single API call to OpenAI.
# We batch 50 at a time — fast, efficient, and within OpenAI's rate limits comfortably.

RETRY_ATTEMPTS = 3
# Number of times to retry an API call if it fails due to a transient error.    
RETRY_SLEEP_SECONDS = 2
# Number of seconds to wait before retrying an API call after a transient error.

@dataclass
class EmbeddedChunk:
    """
    A TextChunk that has been enriched with its vector embedding.

    This is what gets saved to the Cloud SQL chunks table.
    Every field from TextChunk is carried over, plus one new field:
    embedding — the list of 1536 numbers representing this chunk's meaning.

    Fields:
        chunk_id:    Unique identifier. Example: "NCT04788680_chunk_0"
        nct_id:      Which study or paper this chunk belongs to.
        chunk_text:  The actual text content.
        chunk_index: Position in the original document (0, 1, 2...)
        source:      "study" or "paper"
        word_count:  Number of words in this chunk.
        embedding:   1536 floating point numbers from OpenAI.
                     This is the mathematical representation of meaning.
                     Two chunks that mean similar things will have
                     embeddings that are numerically close to each other.
    """
    chunk_id: str
    nct_id: str
    chunk_text: str
    chunk_index: int
    source: str
    word_count: int
    embedding: list[float]
class Embedder:
    """
    Converts TextChunks into EmbeddedChunks using OpenAI's
    text-embedding-3-small model.

    Processes chunks in batches of BATCH_SIZE for efficiency.
    Automatically retries failed API calls up to RETRY_ATTEMPTS times.

    Usage:
        embedder = Embedder()
        embedded = await embedder.embed_chunks(list_of_text_chunks)
    """
    def __init__(self):
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.OPENAI_EMBEDDING_MODEL
        
        logger.info(f"embedder initialized with the model {self._model}")
    async def embed_chunks(self, chunks: list[TextChunk]) -> list[EmbeddedChunk]:
        """
        Converts a list of TextChunks into EmbeddedChunks.

        Splits the input into batches of BATCH_SIZE and processes
        each batch with one OpenAI API call. Much more efficient
        than one API call per chunk.

        Args:
            chunks: List of TextChunk objects from chunker.py

        Returns:
            List of EmbeddedChunk objects — same chunks but now
            each has a 1536-number embedding attached.
            Any chunk that fails to embed is skipped — not fatal.
        """
        if not chunks:
            logger.info(" List is empty and there are no chunks to embed")
            return []
        logger.info(f"Starting embedding |"
                    f"total chunks: {len(chunks)} |"
                    f"batch size: {BATCH_SIZE} |"
                    f"model: {self._model}")
        all_embedded_chunks: list[EmbeddedChunk] = []
        
        batches = self._create_batches(chunks)
        
        for batch_num,batch in enumerate(batches):
            logger.info(f" processing batch {batch_num+1}/{len(batches)}")
            embedded_batch = await self._embed_batch_with_retry(batch=batch,batch_num=batch_num)
            all_embedded_chunks.extend(embedded_batch)
            if batch_num + 1 < len(batches):
                await asyncio.sleep(0.5)
        logger.info(f"Embeddings complete |"
                    f"total embedded chunks: {len(all_embedded_chunks)} |"
                    f"total_input chunks: {len(chunks)} |"
                    f"skipped chunks: {len(chunks) - len(all_embedded_chunks)}")
        return all_embedded_chunks
    async def _create_batches(self,chunks:list[TextChunk]) -> list[list[TextChunk]]:
        """
        Splits a flat list of chunks into smaller batches.

        Example:
            150 chunks with BATCH_SIZE=50 →
            [[chunk_0..chunk_49], [chunk_50..chunk_99], [chunk_100..chunk_149]]

        Args:
            chunks: The full list of chunks to split.

        Returns:
            A list of lists — each inner list is one batch.
        """
        return [chunks[i:i + BATCH_SIZE] for i in range(0, len(chunks), BATCH_SIZE)]
    
    async def _embed_batch_with_retry(self,batch:list[TextChunk],batch_num: int) ->list[EmbeddedChunk]:
        """
        Embeds one batch of chunks, retrying on failure.

        Attempts the embedding up to RETRY_ATTEMPTS times.
        Waits RETRY_SLEEP_SECONDS between each attempt.
        Returns an empty list if all attempts fail — the pipeline
        continues with the remaining batches rather than crashing.

        Args:
            batch:     One batch of TextChunks to embed.
            batch_num: The batch number (for logging only).

        Returns:
            List of EmbeddedChunks for this batch.
            Empty list if all retry attempts failed.
        """
        # Implementation of the retry logic goes here
        for attempt in range(1, RETRY_ATTEMPTS+1):
            try:
                return await self._embed_batch(batch=batch)
            except Exception as e:
                if attempt < RETRY_ATTEMPTS:
                    logger.warning(f"Embedding failed | "
                        f"batch={batch_num + 1} | "
                        f"attempt={attempt}/{RETRY_ATTEMPTS} | "
                        f"error={e} | "
                        f"retrying in {RETRY_SLEEP_SECONDS}s...")
                    await asyncio.sleep(RETRY_SLEEP_SECONDS)
                else:
                    logger.error(f"Embedding failed | "
                        f"batch={batch_num + 1} | "
                        f"attempt={attempt}/{RETRY_ATTEMPTS} | "
                        f"error={e} | "
                        f"no more retries left.")
                    return []
        return []  
    # In case the loop exits without returning, return an empty list
    async def _embed_batch(self,batch:list[TextChunk]) ->list[EmbeddedChunk]:
        """
        This is the method that actually talks to OpenAI.
        It sends up to BATCH_SIZE chunk texts in one request
        and gets back one embedding per chunk.

        Args:
            batch: One batch of TextChunks (up to BATCH_SIZE).

        Returns:
            List of EmbeddedChunks with embeddings attached.

        Raises:
            Exception: If the OpenAI API call fails.
                       The caller (_embed_batch_with_retry) handles this.
        """
        texts = [chunk.chunk_text for chunk in batch]
        response =await self._client.embeddings.create(
            model= self._model,
            input= texts
        )
        embedded_chunks: list[EmbeddedChunk] = []
        for i,chunk in enumerate(batch):
            embedded_chunks.append(
                EmbeddedChunk(
                    chunk_id=chunk.chunk_id,
                    nct_id = chunk.nct_id,
                    chunk_text=chunk.chunk_text,
                    chunk_index=chunk.chunk_index,
                    source=chunk.source,
                    word_count=chunk.word_count,
                    embedding=response.data[i].embedding
                )
            )
        logger.info(
            f"Batch embedded successfully | "
            f"chunks={len(embedded_chunks)} | "
            f"embedding_dims={len(embedded_chunks[0].embedding) if embedded_chunks else 0}"
        )
        return embedded_chunks
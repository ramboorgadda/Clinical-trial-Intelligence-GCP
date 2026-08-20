##############################################################################
# processing/chunker.py
#
# PURPOSE:
#   This file takes a long study document and breaks it into smaller,
#   overlapping pieces of text called "chunks".
#   Each chunk is then sent to OpenAI in the next step (embedder.py)
#   to get its vector embedding — a mathematical representation of
#   what that piece of text MEANS.
#
# WHY DO WE NEED TO CHUNK AT ALL?
#   OpenAI's embedding model has a token limit — it cannot process
#   an entire study document in one shot. A single clinical trial
#   record can easily be 2000-5000 words long. We must break it
#   into smaller pieces first.
#
#   But there is a deeper reason too. If we embed the WHOLE document
#   as one giant chunk, the embedding becomes a blurry average of
#   everything in it. When an agent searches for "sponsor never posted
#   results", a whole-document embedding might miss that signal because
#   it is diluted by all the other content.
#
#   Smaller, focused chunks → sharper, more precise embeddings →
#   agents find exactly what they are looking for.
#
# WHY DO CHUNKS OVERLAP?
#   Imagine cutting a book into pages. If an important sentence
#   happens to fall RIGHT at the cut point — half on page 10,
#   half on page 11 — both pages miss the complete thought.
#
#   Overlapping solves this. Each chunk shares 50 words with the
#   next chunk. So no sentence ever gets cut in half and lost.
#   The overlap is like a safety net at every boundary.
#
# WHAT IS A TextChunk?
#   It is a small Python dataclass — a lightweight container
#   that holds one chunk of text plus metadata about it:
#   which study it came from, which position it is in the
#   document, and what type of content it contains.
#
# SHOULD YOU RUN THIS FILE DIRECTLY?
#   No. This file defines a class. It gets imported and used
#   by run_processing.py. Do not run it directly.
#
# HOW OTHER FILES USE THIS:
#   from processing.chunker import Chunker
#
#   chunker = Chunker()
#   chunks = chunker.chunk_study(parsed_study)
##############################################################################
from dataclasses import dataclass
from typing import Any
from ingestion.document_parser import ParsedStudy, ParsedPaper
from config.logging_config import setup_logging
logger = setup_logging(__name__)

CHUNK_SIZE = 500  # number of words per chunk
CHUNK_OVERLAP = 50  # number of words to overlap between chunks
@dataclass
class TextChunk:
    """
    One chunk of text from a study or paper, ready to be embedded.

    Think of this as a labelled envelope containing a piece of text.
    The label tells us everything about where this text came from
    and where it sits in the original document.

    Fields:
        chunk_id:    Unique identifier for this specific chunk.
                     Format: NCT_ID_chunk_0, NCT_ID_chunk_1, etc.
        nct_id:      Which study this chunk belongs to.
        chunk_text:  The actual text content of this chunk.
        chunk_index: Position of this chunk in the document.
                     0 = first chunk, 1 = second chunk, etc.
        source:      Where this chunk came from.
                     "study"  = from a ClinicalTrials.gov record
                     "paper"  = from a PubMed research paper
        word_count:  How many words are in this chunk.
                     Useful for debugging and quality checks.
    """

    chunk_id:    str
    nct_id:      str
    chunk_text:  str
    chunk_index: int
    source:      str
    word_count:  int

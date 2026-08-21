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

class Chunker:
    """
    Splits study and paper documents into overlapping text chunks.

    Usage:
        chunker = Chunker()
        chunks = chunker.chunk_study(parsed_study)
        chunks = chunker.chunk_paper(parsed_paper)
    """
    # ── CHUNK ONE STUDY ───────────────────────────────────────
    
    def chunk_study(self, study: ParsedStudy) -> list[TextChunk]:
        """
        Takes one ParsedStudy and produces a list of TextChunks.

        First we BUILD the full text by combining all the study's
        important fields into one long string, with clear labels
        so the embedding model knows what each section means.

        Then we SPLIT that long string into overlapping chunks.

        Args:
            study: A clean ParsedStudy object from document_parser.py

        Returns:
            A list of TextChunk objects, ready for embedding.
        """
        full_text = self._build_study_text(study)
        chunks = self._split_into_chunks(text = full_text,
                                        nct_id = study.nct_id,
                                        source = "study")
        logger.info(
            f"Chunked Study |"
            f" NCT_ID={study.nct_id} |"
            f" Chunks_Produced={len(chunks)}")
        
        return chunks
    def chunk_paper(self,paper: ParsedPaper) -> list[TextChunk]:
        """
        Takes one ParsedPaper and produces a list of TextChunks.

        Same two-step process as chunk_study:
        1. Build the full text from all the paper's fields.
        2. Split into overlapping chunks.

        Args:
            paper: A clean ParsedPaper object from document_parser.py

        Returns:
            A list of TextChunk objects, ready for embedding.
        """
        full_text = self._build_paper_text(paper)
        chunks = self._split_into_chunks(text = full_text,
                                        nct_id = paper.nct_id,
                                        source = "paper")
        logger.info(
            f"Chunked Paper |"
            f" NCT_ID={paper.nct_id} |"
            f" Chunks_Produced={len(chunks)}")
        
        return chunks
    # ── CHUNK MANY STUDIES AT ONCE ────────────────────────────
    def chunk_studies(self, studies: list[ParsedStudy]) -> list[TextChunk]:
        """
        Takes a list of ParsedStudy objects and produces a list of TextChunks.

        Args:
            studies: A list of clean ParsedStudy objects from document_parser.py

        Returns:
            A list of TextChunk objects, ready for embedding.
        """
        all_chunks = []
        for study in studies:
            all_chunks.extend(self.chunk_study(study))
        return all_chunks

    # ── CHUNK MANY PAPERS AT ONCE ────────────────────────────
    def chunk_papers(self, papers: list[ParsedPaper]) -> list[TextChunk]:
        """
        Takes a list of ParsedPaper objects and produces a list of TextChunks.

        Args:
            papers: A list of clean ParsedPaper objects from document_parser.py

        Returns:
            A list of TextChunk objects, ready for embedding.
        """
        all_chunks = []
        for paper in papers:
            all_chunks.extend(self.chunk_paper(paper))
        return all_chunks
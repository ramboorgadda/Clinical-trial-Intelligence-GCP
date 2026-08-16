##############################################################################
# ingestion/document_parser.py
#
# PURPOSE:
#   This file cleans up the raw, messy data that comes back from the
#   ClinicalTrials.gov and PubMed APIs.
#   The APIs return deeply nested, inconsistent JSON. This file
#   extracts only the fields we actually need and puts them into
#   clean, predictable, typed Python objects.
#
# WHY THIS FILE EXISTS — THE BOUNDARY PRINCIPLE:
#   Think of this file as a border checkpoint.
#   Messy data comes in from outside (the APIs).
#   Clean data goes out to the rest of our system.
#   Everything AFTER this file — chunking, embedding, agents — only
#   ever sees the clean version. They never have to deal with the
#   API's confusing nested structure.
#
#   This matters because if ClinicalTrials.gov changes their API
#   tomorrow, we only need to fix THIS ONE FILE. Nothing else in
#   the entire system needs to change.
#
# WHAT IS PYDANTIC AND WHY WE USE IT HERE:
#   Pydantic lets us define a "shape" for our data using a class.
#   Once defined, Pydantic automatically checks that every piece
#   of data matches that shape — right types, right fields.
#   If something is wrong, Pydantic raises a clear error immediately
#   instead of causing a confusing crash somewhere else later.
#
# SHOULD YOU RUN THIS FILE DIRECTLY?
#   No — this file defines classes and a parser. It gets imported
#   and used by run_ingestion.py. Do not run it directly.
#
# HOW OTHER FILES USE THIS:
#   from ingestion.document_parser import DocumentParser
#
#   parser = DocumentParser()
#   clean_study = parser.parse_study(raw_study_dict)
#   clean_paper = parser.parse_paper(raw_paper_dict)
##############################################################################
from typing import Any
from pydantic import BaseModel, Field
from config.settings import settings
from config.logging_config import setup_logging
logger = setup_logging(__name__)

# name here is ingestion.document_parser because this file is inside the ingestion folder

# ─────────────────────────────────────────────────────────────
# INTERNAL DATA SHAPES (SCHEMAS)
#
# These two classes define exactly what a "study" and a "paper"
# look like INSIDE our system — after cleaning.
# Every other file in MOSAIC works with these clean shapes,
# never with the raw API data directly.
# ─────────────────────────────────────────────────────────────

class ParsedStudy(BaseModel):
    """
    A clinical trial study, cleaned and structured.

    This is what a "study" means everywhere else in our codebase.
    The chunker reads this. The vector store reads this.
    The agents reason about this. Nobody touches raw API data
    except this one file.
    """

    nct_id: str
    # The unique ID ClinicalTrials.gov assigns to every study.
    # Format: "NCT" followed by 8 digits. Example: "NCT04788680"
    # This is our primary key — every study has exactly one.

    title: str
    # The official name of the study.
    # Example: "A Study of Semaglutide in Adults With Type 2 Diabetes"

    sponsor: str
    # Who is running this study — a pharma company, university,
    # hospital, or government agency.
    # Example: "Novo Nordisk A/S"

    phase: str
    # Which stage of testing this study represents.
    # PHASE1 = small group, mainly testing safety
    # PHASE2 = larger group, testing if it actually works
    # PHASE3 = large scale, final check before approval
    # PHASE4 = monitoring after the drug is already approved
    # NA     = not applicable, e.g. observational studies

    status: str
    # The current state of the study.
    # RECRUITING, ACTIVE_NOT_RECRUITING, COMPLETED, TERMINATED, etc.

    conditions: list[str]
    # The medical conditions this study is investigating.
    # Example: ["Type 2 Diabetes", "Obesity"]

    interventions: list[str]
    # The drugs, devices, or procedures being tested.
    # Example: ["Semaglutide 2.4mg", "Placebo"]

    primary_outcome: str
    # The single most important thing this study promised to measure
    # before it started. This is the field our Broken Promises agent
    # cares about most — did the study still measure this at the end?
    # Example: "Change in HbA1c at 26 weeks"

    secondary_outcomes: list[str]
    # Additional things the study measured beyond the primary outcome.

    start_date: str
    # When the study began enrolling participants. Format: "YYYY-MM"

    completion_date: str
    # When the study finished or is expected to finish. Format: "YYYY-MM"

    results_posted: bool
    # Whether the sponsor has posted results to ClinicalTrials.gov.
    # If this is False AND status is COMPLETED, that is a signal
    # our Missing Results agent looks for.

    enrollment: int
    # How many participants were enrolled, or planned to be enrolled.

    protocol_amendments: list[dict[str, Any]]
    # Every time the study design was officially changed mid-study.
    # Multiple amendments can hint at instability in the study design.

    raw_data: dict[str, Any]
    # The complete original API response, kept exactly as received.
    # We keep this "just in case" — if we ever need a field we did
    # not extract above, it is still here. Nothing is ever thrown away.

    parsed_at: str
    # The timestamp of when this record was cleaned.
    # Useful later for knowing how fresh the data is.
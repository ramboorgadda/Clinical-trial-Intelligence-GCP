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
from curses import raw
from typing import Any
from datetime import datetime
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

class ParsedPaper(BaseModel):
    """
    A PubMed research paper, cleaned and structured.

    Same idea as ParsedStudy — this is what a "paper" means
    everywhere else in our codebase.
    """

    pmid: str
    # PubMed's unique ID for this paper. Example: "38234567"

    title: str
    abstract: str
    journal: str
    pub_date: str
    authors: list[str]
    nct_ids_referenced: list[str]
    # Which clinical trials this paper mentions.
    # Used to link a paper back to the study it discusses.

    source: str = "pubmed"
    # Always "pubmed" — tags this record so downstream code knows
    # it came from a research paper, not a clinical trial filing.

    word_count: int
    # Roughly how many words are in the abstract.
    # A very short abstract (under 50 words) often signals that
    # the paper does not have much useful detail for our agents.

    parsed_at: str
    
# ─────────────────────────────────────────────────────────────
# THE PARSER CLASS
#
# This class does the actual work of turning messy raw data
# into the clean ParsedStudy and ParsedPaper shapes above.
# It is "stateless" — it does not remember anything between calls.
# You can create one DocumentParser and reuse it for everything.
# ─────────────────────────────────────────────────────────────

class DocumentParser:
    """
    Cleans and structures raw API data into our internal shapes.

    This class is stateless — it does not remember anything between calls.
    You can create one DocumentParser and reuse it for everything.
    usage:
        parser = DocumentParser()
        clean_study = parser.parse_study(raw_study_dict)
        clean_paper = parser.parse_paper(raw_paper_dict)
    """

    def parse_study(self, raw_study: dict[str, Any]) -> ParsedStudy | None:
        """
        Cleans a single raw study record from ClinicalTrials.gov.

        Args:
            raw_study (dict): The raw JSON data for a study.

        Returns:
            ParsedStudy | None: The cleaned study record, or None if parsing failed.
        """
        try:
            # navigate the nested section
            # The API wraps almost everything inside "protocolSection".
            # Think of this as opening a series of boxes inside boxes.
            protocol = raw_study.get("protocolSection",{})
            id_module= protocol.get("identificationModule",{})
            status_module = protocol.get("statusModule",{})
            sponsor_module = protocol.get("sponsorCollaboratorsModule",{})
            conditions_module = protocol.get("conditionsModule",{})
            design_module = protocol.get("designModule",{})
            outcomes_module = protocol.get("outcomesModule",{})
            interventions_module = protocol.get("armInterventionsModule",{})
            # Each "module" is one box inside the bigger box.
            # We open each one we need and store it in a short variable
            # so the rest of this method stays readable.
            results_section = raw_study.get("resultsSection",{})
            has_results = bool(results_section)
            # resultsSection is a SEPARATE top-level box, outside
            # protocolSection. If it exists and is not empty,
            # the sponsor has posted results for this study.
            # bool({}) is False, bool({"some": "data"}) is True.
            # ── EXTRACT THE NCT ID FIRST ───────────────────────
            nct_id = id_module.get("nctId")
            if not nct_id:
                logger.warning(f"Study missing nctId, skipping: {raw_study}")
                return None
            title = ( id_module.get("officialTitle") or
                    id_module.get("briefTitle") or
                    "" )
            # Try the full official title first.
            # Some studies only have a short "brief" title — use that
            # as a fallback. The "or" chain tries each option in order
            # until one of them is not empty.
            # ── EXTRACT THE SPONSOR ────────────────────────────
            sponsor = (sponsor_module.get("leadSponsor",{}).get("name", "Unknown sponsor"))
            # Chain of .get() calls — each one safely returns an empty
            # dict {} if the key is missing, so the NEXT .get() never
            # crashes trying to call .get() on something that is None.
            # Extract the Phase
            phase = design_module.get("phases",["NA"])
            phase = phase[0] if phase else "NA"
            # ── EXTRACT STATUS, CONDITIONS, INTERVENTIONS ──────
            status = status_module.get("overallStatus", "Unknown") 
            conditions = conditions_module.get("conditions", [])
            interventions = [ i.get("name","") for i in interventions_module.get("interventions",[]) if i.get("name")]
            # List comprehension: go through every intervention entry,
            # pull out its "name" field, and only keep ones that
            # actually have a name (skip empty/broken entries).
            primary_outcome = outcomes_module.get("primaryOutcomes",[])
            primary_outcome = (primary_outcome[0].get("name") if primary_outcome else "")
            # A study can technically list more than one primary outcome,
            # but in practice the first one is the main one.
            # The "if primary_outcomes_list else" guards against an
            # empty list — calling [0] on an empty list would crash.
            
            secondary_outcomes = [o.get("measure") for o in outcomes_module.get("secondaryOutcomes",[]) if o.get("measure")]
            
            start_date = (
                status_module
                .get("startDateStruct", {})
                .get("date", "")
            )

            completion_date = (
                status_module
                .get("primaryCompletionDateStruct", {})
                .get("date", "")
                or status_module
                .get("completionDateStruct", {})
                .get("date", "")
            )
            # Try "primary completion date" first — this is the date
            # the main outcome was actually measured.
            # Fall back to the general "completion date" if the
            # primary one is not available.
            
            # ── EXTRACT ENROLLMENT NUMBER ──────────────────────
            enrollment_info = design_module.get("enrollmentInfo",{})
            enrollment = enrollment_info.get("count",0)
            try:
                enrollment = int(enrollment)
            except (ValueError, TypeError):
                enrollment = 0
            annotations      = raw_study.get("annotationSection", {})
            amendment_module = annotations.get("annotationModule", {})
            amendments       = amendment_module.get("unpostedAnnotation", {})
            protocol_amendments = []
            if amendments:
                protocol_amendments = [
                    {
                        "date":        amendments.get("unpostedResponsibleParty", ""),
                        "description": str(amendments),
                    }
                ]
            # The amendment data in the API is structured inconsistently
            # across different studies. We capture whatever is there
            # in a simple form — our agents can still reason about it
            # even in this rough shape.
                
            # ── BUILD THE FINAL CLEAN OBJECT ───────────────────
            return ParsedStudy(
                nct_id=nct_id,
                title=title,
                sponsor=sponsor,
                phase=phase,
                status=status,
                conditions=conditions,
                interventions=interventions,
                primary_outcome=primary_outcome,
                secondary_outcomes=secondary_outcomes,
                start_date=start_date,
                completion_date=completion_date,
                results_posted=has_results,
                enrollment=enrollment,
                protocol_amendments=protocol_amendments,
                raw_data=raw_study,
                parsed_at=datetime.utcnow().isoformat(),
            )
        except Exception as e:
            nct_id = raw_study.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "unknown")
            logger.error(f"Failed to parse study {nct_id}: {e}")
            return None
##############################################################################
# agents/broken_promises_agent.py
#
# PURPOSE:
#   Detects outcome switching — when a clinical trial changes what it
#   promised to measure AFTER the study has already begun.
#
# WHY OUTCOME SWITCHING MATTERS:
#   Before a trial starts, sponsors must register exactly what they
#   plan to measure as the primary outcome.
#   Example: "Reduction in HbA1c at 26 weeks"
#
#   If the drug fails to show results on that measure, some sponsors
#   quietly change the primary outcome to something the drug DID work for.
#   This is called "outcome switching" — it is scientific fraud.
#   The published paper then reports success on the NEW outcome
#   while hiding that the original outcome was a failure.
#
#   This agent finds these cases by comparing what was originally
#   registered against what was actually measured and reported.
##############################################################################
import json
import re
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from graph.state import MosaicState,SignalOutput
from memory.procedural_store import ProceduralStore
from memory.episodic_store import EpisodicStore
from tools.search_tools import (
    search_studies_by_meaning,
    search_past_episodes,
    save_episode,
    get_sponsor_profile,
    update_sponsor_profile,
)
from tools.clinical_tools import fetch_study_details, get_study_amendments
from config.settings import settings
from config.logging_config import setup_logging

logger = setup_logging(__name__)

AGENT_NAME = "broken_promises_agent"
SIGNAL_TYPE = "broken_promises"
AGENT_TOOLS = [
    search_studies_by_meaning,
    search_past_episodes,
    save_episode,
    get_sponsor_profile,
    update_sponsor_profile,
    fetch_study_details,
    get_study_amendments,
    # get_study_amendments is unique to this agent —
    # it fetches the full protocol amendment history which contains
    # evidence of when and how outcomes were changed.
]
_procedural = ProceduralStore()
_episodic   = EpisodicStore()

_llm = ChatOpenAI(
    model=settings.openai_chat_model,
    temperature=0.1,
    api_key=settings.openai_api_key,
).bind_tools(AGENT_TOOLS)
async def broken_promises_node(state: MosaicState) -> dict:
    """
    Broken Promises Agent node — detects outcome switching in clinical trials.
    Runs in parallel with the other 5 specialist agents.
    """
    logger.info(f"{AGENT_NAME} | Starting broken promises node")
    try:
       pass
    except Exception as e:
        logger.error(f"{AGENT_NAME} | Error | {e}")
        return {
            "error_log":        state.get("error_log", []) + [f"{AGENT_NAME}: {str(e)}"],
            "agents_activated": state.get("agents_activated", []) + [AGENT_NAME],
        }
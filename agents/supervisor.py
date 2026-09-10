##############################################################################
# agents/supervisor.py
#
# PURPOSE:
#   The Supervisor is the ORCHESTRATOR of the entire MOSAIC agent graph.
#   It has two jobs and two jobs only:
#
#   Job 1 — ROUTE (supervisor_route):
#     Read the incoming task, prepare the shared state, and hand off
#     to all six specialist agents simultaneously.
#     Think of it as a project manager who reads a client brief,
#     understands what needs investigating, and assigns work to
#     the right specialists.
#
#   Job 2 — COMPILE (supervisor_compile):
#     After all six specialists finish, read every signal they found,
#     rank them by priority, and write one final intelligence brief.
#     Think of it as the project manager collecting everyone's findings
#     and writing the executive summary for the client.
#
# WHAT THE SUPERVISOR DOES NOT DO:
#   The supervisor does NOT analyse any studies itself.
#   It does NOT call any tools.
#   It does NOT search the database.
#   Its only job is coordination — routing work and compiling output.
#   This separation keeps each component focused and testable.
#
# TWO FUNCTIONS — NOT A CLASS:
#   We define the supervisor as two plain async functions rather than
#   a class because LangGraph nodes are just functions — they receive
#   state, do work, and return updated state. No object needed.
#
# SHOULD YOU RUN THIS FILE DIRECTLY?
#   No. graph_builder.py imports these functions and wires them
#   into the LangGraph StateGraph as nodes.
##############################################################################

import uuid
# uuid.uuid4() generates a unique run ID for each analysis session.
# Every time someone calls POST /api/v1/analyze, a new run_id is
# generated so we can track all signals from that specific run.
from langchain_openai import ChatOpenAI
# ChatOpenAI is LangChain's wrapper around OpenAI's GPT models.
# It handles authentication, request formatting, and response parsing.
# We use it for the compile step — GPT-4o writes the final brief.
from langchain_core.messages import HumanMessage,SystemMessage
# HumanMessage = a message from the user (or in our case, the task)
# SystemMessage = instructions we give to GPT-4o before the conversation
# These are the standard message types in LangChain's message system.

from graph.state import StateGraph,MosaicState
from config.settings import settings
from config.logging_config import setup_logger
logger = setup_logger(__name__)

llm = ChatOpenAI(
    model=settings.openai_chat_model,
    temperature=0.1,
    api_key=settings.openai_api_key
)

##############################################################################
# FUNCTION 1: supervisor_route
#
# This is the FIRST node in the LangGraph graph.
# It runs before any specialist agent.
# Its job is to initialise the run and prepare state for the specialists.
##############################################################################

async def supervisor_route(state: MosaicState) -> MosaicState:
    """
    The entry point of every MOSAIC analysis run.

    WHAT THIS FUNCTION DOES:
    1. Generates a unique run ID for this analysis session
    2. Logs what task is being investigated
    3. Returns an updated state that all specialists will receive

    WHY SO SIMPLE?
    The supervisor does NOT need to read the task and decide which
    specialists to activate — we always run ALL six specialists in
    parallel for every task. This is by design:
    - Different agents may find different signals in the same task
    - Running all six costs the same time as running one (parallel)
    - We never miss a signal type by selectively routing

    LANGGRAPH NODE CONTRACT:
    Every LangGraph node must:
    - Accept: the current MosaicState
    - Return: a dict of ONLY the fields that changed
    LangGraph automatically merges the returned dict into the full state.
    You do not return the entire state — just your changes.

    Args:
        state: The current MosaicState from LangGraph.

    Returns:
        Dict with updated run_id, agents_activated, and signals fields.
    """
    run_id = str(uuid.uuid4())
    # Generate a unique ID for this specific analysis run.
    # Every signal generated during this run will be tagged with this ID.
    # This lets us later query: "show me all signals from run X."
    state.run_id = run_id
    logger.info(
        f"Supervisor routing | "
        f"run_id={run_id} | "
        f"task='{state.get('task', '')[:80]}'"
        # state.get('task', '') safely reads the task from state.
        # [:80] takes the first 80 characters — prevents very long
        # task descriptions from flooding the log.
    )
    return {
        "run_id": run_id, # Set the run ID — all specialist agents will see this in state.

        "agents_activated": [],
        # Start with empty list — each specialist will ADD its name
        # to this list when it runs. By the end, this list shows
        # exactly which agents were activated.

        "signals":          [],
        # Start with empty signals list — each specialist APPENDS
        # its found signals to this list.
        # Because MosaicState uses add_messages pattern for signals,
        # LangGraph merges rather than replaces.

        "run_complete":     False,
        # False = run is in progress.
        # supervisor_compile sets this to True when done.

        "error_log":        [],
        # Empty error log at start — agents write errors here
        # if something goes wrong during their run.
    }
##############################################################################
# FUNCTION 2: supervisor_compile
#
# This is the LAST node before END in the LangGraph graph.
# It runs AFTER all six specialists have finished.
# Its job is to read every signal and write the final brief.
##############################################################################
async def supervisor_compile(state: MosaicState) -> dict:
    """
    Reads all agent signals and compiles the final intelligence brief.

    WHEN THIS RUNS:
    LangGraph calls this node only after ALL six specialist nodes
    have completed. This is guaranteed by the graph structure in
    graph_builder.py — all specialists connect to this node.

    WHAT THIS FUNCTION DOES:
    1. Collects all signals from state (from all 6 agents)
    2. Separates high-confidence signals from those needing review
    3. Uses GPT-4o to write a professional intelligence brief
    4. Returns the completed state

    WHY USE GPT-4o TO WRITE THE BRIEF?
    The raw signals are structured data — JSON with fields like
    summary, confidence, nct_id. They are accurate but not readable.
    GPT-4o transforms them into a professional narrative brief that
    a human analyst can read and act on immediately.
    The signals provide the FACTS. GPT-4o provides the WRITING.

    Args:
        state: The full MosaicState — now populated with all agent signals.

    Returns:
        Dict with final_brief, run_complete=True, and summary stats.
    """
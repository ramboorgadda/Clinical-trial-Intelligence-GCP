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

from graph.state import SignalOutput, StateGraph,MosaicState
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
    
    signals = state.get("signals",[])
    agents_activated = state.get("agents_activated",[])
    task = state.get("task","")
    
    logger.info(f"Supervisor Compiling Brief |"
                f"Signals = {len(signals)} |"
                f"Agents Activated = {len(agents_activated)} |"
                f"Task = {task}")
    if not signals:
        logger.info("No signals found returning clean brief")
        return {
            "final_brief": ("**EXECUTIVE SUMMARY:** Analysis complete. "
                "No significant research integrity signals were detected "
                "for the specified task and study set."),
            "run_complete": True,
            "agents_activated": agents_activated
        }
    
    # ── SEPARATE SIGNALS BY REVIEW STATUS ────────────────────────────────
    high_confidence_signals = [s for s in signals if s.get("confidence",0) >= 0.6]
    review_signals = [s for s in signals if s.get("confidence",0) < 0.6]
    
    signals_text = _format_signals_for_llm(signals)
    # Convert the list of signal dicts into a clean text block
    # that GPT-4o can read and summarise effectively.
    # Explained in detail below in _format_signals_for_llm.
    system_prompt = """You are the Chief Intelligence Officer of MOSAIC —
    a clinical trial research integrity system. Your job is to compile
    a professional executive intelligence brief from the signals generated
    by specialist AI agents.
    BRIEF FORMAT:
    1. EXECUTIVE SUMMARY — 2-3 sentences summarising the most critical findings
    2. SIGNALS BY PRIORITY — each signal as a numbered item with:
    - What was found
    - Why it matters
    - What action to take
    3. SIGNALS REQUIRING HUMAN REVIEW — list any low-confidence signals
    4. PIPELINE HEALTH — note any errors or issues during the run

    TONE: Professional, factual, actionable. Write as if briefing a
    senior compliance officer or investigative journalist.
    Be specific — include NCT IDs, sponsor names, and exact timeframes.
    """
    human_prompt = f"""
    ANALYSIS TASK: {task}

    SIGNALS FOUND BY AGENTS:
    {signals_text}

    HIGH CONFIDENCE SIGNALS: {len(high_confidence_signals)}
    SIGNALS REQUIRING REVIEW: {len(review_signals)}
    AGENTS ACTIVATED: {', '.join(agents_activated)}

    Please compile the final intelligence brief now.
    """
    # The human prompt provides the actual content — the task and
    # all the signals. GPT-4o uses this to write the brief.

    # ── CALL GPT-4o ───────────────────────────────────────────────────────
    try:
        response = await llm.invoke(
            [SystemMessage(content=system_prompt), 
            HumanMessage(content=human_prompt)]
            # ainvoke() is the ASYNC version of invoke().
            # "a" prefix = async in LangChain's naming convention.
            # We await it because it makes a network call to OpenAI.
            # The list contains our two messages — system first, then human.
            # GPT-4o reads both and generates the brief.
            )
        final_brief = response.content
        logger.info(
            f"Brief compiled successfully | "
            f"signals_included={len(signals)} | "
            f"brief_length={len(final_brief)} chars"
        )

    except Exception as e:
        logger.error(f"LLM brief compilation error: {e}")
        final_brief = _fallback_brief(signals, agents_activated, task)
    return {
            "final_brief": final_brief,
            "run_complete": True,
            "total_signals": len(signals),
            "signals_requiring_review": len(review_signals),
            "agents_activated": agents_activated
        }
##############################################################################
# PRIVATE HELPER: _format_signals_for_llm
##############################################################################
def _format_signals_for_llm(signals: list[SignalOutput]) -> str:
    """
    Converts a list of signal dicts into a clean, readable text block
    that GPT-4o can effectively summarise into the final brief.

    WHY FORMAT BEFORE SENDING TO GPT-4o?
    Raw signal dicts are JSON — full of curly braces and quotes.
    GPT-4o works better with plain, labelled text than raw JSON.
    Formatting the signals into clear sections produces better briefs.

    Args:
        signals: List of SignalOutput dicts from specialist agents.

    Returns:
        A formatted string with all signals clearly laid out.
    """
    if not signals:
        return "No Signal generated"
    lines = []
    for i, signal in enumerate(signals, start=1):
        lines.append(f"SIGNAL {i}:")
        lines.append(f" Agent {signal.get('agent','unknown')}")
        lines.append(f" Type {signal.get('type','unknown')}")
        lines.append(f" NCT ID: {signal.get('nct_id','unknown')}")
        lines.append(f" Confidence: {signal.get('confidence',0.0):.2f}")
        lines.append(f" Summary: {signal.get('summary','')}")
        lines.append("")  # Add a blank line between signals for readability
    return "\n".join(lines)
##############################################################################
# PRIVATE HELPER: _fallback_brief
##############################################################################

def _fallback_brief(
    signals:          list,
    agents_activated: list,
    task:             str,
) -> str:
    """
    Generates a basic structured brief WITHOUT using GPT-4o.

    Called when the LLM call fails — ensures the API always returns
    something useful even if OpenAI is down or rate-limited.
    The output is less polished than the GPT-4o brief but contains
    all the factual information the caller needs.

    Args:
        signals:          All signals from the run.
        agents_activated: Which agents ran.
        task:             The original analysis task.

    Returns:
        A plain text brief built directly from signal data.
    """

    lines = [
        "**EXECUTIVE SUMMARY:**",
        f"Analysis complete. {len(signals)} signal(s) detected.",
        "",
        "**SIGNALS BY PRIORITY:**",
        "",
    ]

    for i, signal in enumerate(signals, start=1):
        lines.append(
            f"{i}. **{signal.get('nct_id', 'Unknown')} "
            f"- {signal.get('signal_type', 'Unknown')}:**"
        )
        lines.append(f"   {signal.get('summary', 'No summary available.')}")
        lines.append(
            f"   Confidence: {signal.get('confidence', 0.0):.2f} | "
            f"Agent: {signal.get('agent', 'unknown')}"
        )
        lines.append("")

    lines.append(f"**AGENTS ACTIVATED:** {', '.join(agents_activated)}")
    lines.append(
        "\n*Note: This brief was generated without LLM assistance "
        "due to a temporary error. Please review raw signals directly.*"
    )

    return "\n".join(lines)
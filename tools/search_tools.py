##############################################################################
# tools/search_tools.py
#
# PURPOSE:
#   This file defines the TOOLS that our LangGraph agents use to
#   interact with the outside world — the database, the memory layer,
#   and the vector search system.
#
# WHAT IS A LANGRAPH TOOL?
#   In LangGraph, a "tool" is a function that an agent can CHOOSE to call.
#   The agent does not call tools directly in code — instead, GPT-4o
#   DECIDES which tools to call based on what it is trying to find out.
#
#   Think of it like giving a detective a set of capabilities:
#     Tool 1: "Search the evidence database by meaning"
#     Tool 2: "Look up what I found about this sponsor before"
#     Tool 3: "Check if I have investigated this study before"
#
#   The detective (agent) reads the case file and DECIDES:
#   "I need to search for studies with missing results first,
#    then check the sponsor's track record."
#   It calls those tools in that order — autonomously.
#
# WHY ARE TOOLS DEFINED SEPARATELY FROM AGENTS?
#   Clean separation of concerns:
#   - Tools know HOW to fetch data (database queries, API calls)
#   - Agents know WHAT to look for and HOW to reason about findings
#   - Tools are REUSABLE — multiple agents can use the same tool
#
#   Example: search_studies_by_meaning is used by FIVE different agents.
#   If we put it inside one agent, the other four could not use it.
#   Defining it here makes it available to everyone.
#
# HOW LANGRAPH TOOLS WORK — THE @tool DECORATOR:
#   @tool is a LangChain/LangGraph decorator that transforms a regular
#   Python function into a tool that GPT-4o can call.
#   It reads the function's docstring to understand what the tool does.
#   It reads the function's type hints to know what parameters to pass.
#   GPT-4o uses this information to decide WHEN and HOW to call each tool.
#
#   IMPORTANT: The docstring is NOT just for human readers —
#   GPT-4o reads it to understand what the tool does.
#   Write docstrings as if you are explaining to the AI what this tool is for.
#
# SHOULD YOU RUN THIS FILE DIRECTLY?
#   No. Agents import tools from this file. Do not run it directly.
##############################################################################
import asyncio
import json
from langchain_core.tools import tool

from processing.vector_store import VectorStore

from memory.episodic_store import EpisodicStore
from memory.semantic_store import SemanticStore

from config.logging_config import setup_logger
logger = setup_logger(__name__)


##############################################################################
# SHARED STORE INSTANCES
#
# We create ONE instance of each store at MODULE LEVEL.
# "Module level" means outside any function or class —
# at the top level of this file.
#
# WHY ONE SHARED INSTANCE?
# Creating a new database connection pool for every tool call would be
# extremely wasteful — opening a connection takes ~100-200ms.
# With 6 agents each calling 5-10 tools per run, that is 30-60
# connection openings per analysis run. Very slow.
#
# Instead, we create ONE instance per store at startup.
# All tool calls share the same instance and its connection pool.
# The pool handles multiple simultaneous calls efficiently.
#
# WHY NOT CREATE THESE INSIDE EACH TOOL FUNCTION?
# Tool functions are called by LangGraph many times during one run.
# If we created stores inside each function, we would create and
# destroy connection pools on every single tool call — catastrophic.
##############################################################################

_vector_store = VectorStore()
_episodic_store = EpisodicStore()
_semantic_store = SemanticStore()

##############################################################################
# THE ASYNC BRIDGE PATTERN
#
# LangGraph tools are called SYNCHRONOUSLY by the framework —
# LangGraph does not await tool functions.
# But ALL our store methods are ASYNC — they use await.
#
# This creates a conflict:
#   LangGraph: "call this tool function synchronously"
#   Our code:  "but our database functions need await"
#
# The solution is _run_async() — a helper that runs an async
# function synchronously by using asyncio.
#
# HOW IT WORKS:
#   asyncio.get_event_loop()          → get the current async event loop
#   .run_until_complete(coroutine)    → run the coroutine and wait for it
#
# This bridges the sync/async boundary cleanly.
# Every tool function calls _run_async() to run its async database call.
##############################################################################
def _run_async(coroutine):
    """
    Runs an async coroutine synchronously.

    WHAT IS A COROUTINE?
    When you call an async function WITHOUT await, Python gives you
    back a "coroutine" — a suspended function that has not run yet.
    Example:
      result = store.search(...)      → coroutine (not run yet)
      result = await store.search(...)→ actual result (ran and waited)

    This helper takes that suspended coroutine and runs it to completion
    using the event loop — giving us the actual result synchronously.

    Args:
        coroutine: An unawaited async function call.

    Returns:
        Whatever the async function would have returned with await.
    """
    
    loop = asyncio.get_event_loop()
    # get_event_loop() returns the currently running asyncio event loop.
    # The event loop is the engine that manages all async operations.
    # LangGraph runs inside an event loop, so there is always one available.
    return loop.run_until_complete(coroutine)
    # run_until_complete() takes our coroutine, runs it inside the loop,
    # waits for it to finish, and returns the result.
    # It is the bridge between the synchronous world (LangGraph tools)
    # and the async world (our database functions).
    
##############################################################################
# TOOL 1: search_studies_by_meaning
##############################################################################
@tool
def search_studies_by_meaning(
    query: str,
    top_k: int =5,
    source_filter: str = "study") -> str:
    # @tool transforms this regular function into a LangGraph tool.
    # GPT-4o reads the function name, docstring, and parameter types
    # to understand what this tool does and when to call it.
    #
    # The function name "search_studies_by_meaning" tells GPT-4o
    # that this tool searches studies semantically.
    #
    # Parameters:
    # query: str           → GPT-4o passes the search question as a string
    # top_k: int = 5       → how many results to return (default 5)
    # source_filter: str   → "study" or "paper" (default "study")
    #
    # -> str               → tools MUST return strings for LangGraph
    """
    Search clinical trial studies using semantic similarity.

    Use this tool when you need to find studies related to a specific
    topic, condition, sponsor behaviour, or research integrity issue.
    The search works by MEANING — not exact keyword matching.

    For example:
    - "studies where sponsor never posted results" finds studies about
      missing results even if they use different words
    - "Novo Nordisk cardiovascular trials" finds all relevant chunks

    Args:
        query:         What to search for. Write as a natural language question.
        top_k:         How many results to return. Default 5. Max 10.
        source_filter: "study" to search trial records only.
                       "paper" to search PubMed papers only.
                       Leave as "study" for most agent tasks.

    Returns:
        JSON string containing matching study chunks with similarity scores.
    """
    logger.info(
            f"Tool called: search_studies_by_meaning |"
            f"query = '{query[:60]}' | top_k = {top_k}")
    try:
        results = _run_async(_vector_store.search(query_text=query, 
                        top_k=top_k, 
                        source_filter=source_filter)
                        )
        if not results:
            return json.dumps({
                            "results": [],
                            "message": "No relevant studies found for this query.",
                            "query":   query,
                            }
                            )
        return json.dumps({
                            "results": results,
                            "count": len(results),
                            "query": query,
                            },indent=2, default=str)
    except Exception as e:
        logger.error(f"Error in search_studies_by_meaning failed: {e}")
        return json.dumps({"error": str(e),"results":[]})
##############################################################################
# TOOL 2: search_past_episodes
##############################################################################
@tool
def search_past_episodes(
    query: str,
    agent_name: str,
    top_k: int = 5,
) -> str:
    """
    Search through past agent reasoning sessions (episodic memory).

    Use this tool at the START of every investigation to check if
    you have found similar signals before. This prevents duplicate
    work and gives you historical context.

    Ask questions like:
    - "previous findings about missing results from this sponsor"
    - "past investigations of NCT04788680"
    - "episodes where outcome switching was detected"

    Args:
        query:      What to search for in past episodes.
        agent_name: Your own agent name — filters to YOUR past sessions.
                    Example: "missing_results_agent"
        top_k:      How many past episodes to retrieve. Default 3.

    Returns:
        JSON string with the most relevant past episodes.
        If empty, this is the first time investigating this topic.
    """
    logger.info(f"Tool called: search_past_episodes | "
        f"agent={agent_name} | query='{query[:60]}'")
    try:
        episodes = _run_async(_episodic_store.search_episodes(query_text=query, 
                        agent_name=agent_name,
                        top_k=top_k, 
                    )
                )
        if not episodes:
            return json.dumps({
                "results": [],
                "message": "No relevant past episodes found. "
                            "This appears to be a new type of investigation.",
                "query": query,
            })
        return json.dumps({
            "results": episodes,
            "count": len(episodes),
            "query": query,
        }, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error in search_past_episodes failed: {e}")
        return json.dumps({"error": str(e),"results":[]})
##############################################################################
# TOOL 3: save_episode
##############################################################################

@tool
def save_episode(
    agent_name: str,
    content: str,
    nct_id: str = "",
    outcome: str ="completed",
) ->str:
    """
    Save the current reasoning session as an episode in memory.

    Call this tool at the END of every investigation — after you have
    drawn your conclusions. Saving episodes builds your long-term memory
    so future sessions can benefit from what you found today.

    Write the content as a detailed case note:
    - What study you investigated
    - What the sponsor's behaviour was
    - What signals you found or did not find
    - Why you reached your conclusion

    Args:
        agent_name: Your own agent name.
                    Example: "missing_results_agent"
        content:    Detailed description of what you investigated and found.
                    Write this like a detective's case note.
        nct_id:     The NCT ID of the study you investigated.
                    Leave empty if investigating multiple studies.
        outcome:    What happened: "signal_generated", "no_signal",
                    "sent_to_review", or "completed".

    Returns:
        JSON string confirming the episode was saved with its ID.
    """
    logger.info(f"Tool called: save_episode | "
                f"agent={agent_name} | nct_id={nct_id} | outcome={outcome}")
    try:
        
        episode_id = _run_async(_episodic_store.save_episode(
            agent_name=agent_name,
            content=content,
            nct_id=nct_id if nct_id else None,
            outcome=outcome,
        ))
        
        return json.dumps({
            "success": True,
            "episode_id": episode_id,
            "message": "Episode saved to long term memory successfully.",
            "agent_name": agent_name})
    except Exception as e:
        logger.error(f"Error in save_episode failed: {e}")
        return json.dumps({"success": False, "error": str(e)})
##############################################################################
# TOOL 4: get_sponsor_profile
##############################################################################
@tool
def get_sponsor_profile(sponsor_name: str) -> str:
    """
    Retrieve everything MOSAIC knows about a specific research sponsor.

    Use this tool when evaluating a study to understand the sponsor's
    historical behaviour — their compliance record, broken promises,
    average delays, and credibility score.

    A credibility score below 0.6 is concerning.
    A credibility score below 0.4 is a serious red flag.

    Args:
        sponsor_name: The exact sponsor name as it appears in the study.
                      Example: "Novo Nordisk A/S"
                      Example: "National Cancer Institute (NCI)"

    Returns:
        JSON string with the sponsor's full profile.
        If the sponsor is new (never analysed before), returns a message
        indicating no historical data is available.
    """

    logger.info(
        f"Tool called: get_sponsor_profile | sponsor={sponsor_name}"
    )

    try:
        profile = _run_async(
            _semantic_store.get_sponsor_profile(sponsor=sponsor_name)
        )

        if profile is None:
            # This sponsor has never been analysed before.
            # Return a clear message — the agent knows to proceed with
            # caution and lower confidence due to lack of data.
            return json.dumps({
                "sponsor":  sponsor_name,
                "found":    False,
                "message":  f"No historical data for '{sponsor_name}'. "
                            "This sponsor has not been analysed before. "
                            "Proceed with lower confidence.",
            }, indent=2)

        return json.dumps({
            "found":   True,
            "profile": profile,
            # The full profile dict:
            # credibility_score, total_studies, results_posted,
            # results_missing, broken_promises, avg_delay_days
        }, indent=2, default=str)

    except Exception as e:
        logger.error(f"get_sponsor_profile failed | error={e}")
        return json.dumps({"error": str(e), "found": False})
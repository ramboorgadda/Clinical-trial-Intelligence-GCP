Step 1  → config/logging_config.py + config/settings.py + .env
Step 2  → requirements.txt + pyproject.toml + project structure bash commands
Step 3  → ingestion/clinical_trials_client.py
Step 4  → ingestion/pubmed_client.py
Step 5  → ingestion/document_parser.py
Step 6  → ingestion/gcs_store.py
Step 7  → ingestion/run_ingestion.py  ← first real run here
Step 8  → processing/chunker.py
Step 9  → processing/embedder.py
Step 10 → processing/vector_store.py
Step 11 → processing/run_processing.py  ← second real run here
Step 12 → memory/episodic_store.py
Step 13 → memory/procedural_store.py
Step 14 → memory/semantic_store.py
Step 15 → tools/search_tools.py
Step 16 → tools/clinical_tools.py
Step 17 → tools/pubmed_tools.py
Step 18 → graph/state.py
Step 19 → agents/supervisor.py
Step 20 → agents/broken_promises_agent.py
Step 21 → agents/missing_results_agent.py
Step 22 → agents/track_record_agent.py
Step 23 → agents/pattern_finder_agent.py
Step 24 → agents/side_effect_agent.py
Step 25 → agents/timeline_agent.py
Step 26 → graph/graph_builder.py
Step 27 → graph/hitl.py
Step 28 → api/schemas.py
Step 29 → api/dependencies.py
Step 30 → api/routers/analysis.py
Step 31 → api/routers/signals.py
Step 32 → api/routers/review.py
Step 33 → api/routers/memory.py
Step 34 → api/main.py  ← third real run here (local)
Step 35 → deployment/Dockerfile + deploy.sh  ← fourth real run (Cloud Run)

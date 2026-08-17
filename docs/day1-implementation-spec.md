# Day 1 implementation status

> Historical baseline. The runtime, evidence-state, inventory, probe, bilingual
> UI, and submission-preparation work has progressed beyond this Day 1 snapshot.
> Use README.md and the current Notion 01/02 pages for present behaviour.

This repository implements the Notion Day 1 specification with local fixtures and mocks only.

The contracts live in `app/contracts/models.py`. The decision-led loop lives in `app/agents/orchestrator.py`; it searches for media only after the Story Agent requests evidence. `app/mcp/box_client.py` and `app/video/gemini_client.py` expose protocol boundaries for later, verified adapters.

At Day 1, live Box MCP, Gemini, Garmin Connect, and Google Cloud Agent Builder /
Agent Platform integrations were intentionally out of scope and unverified. The
current project now has synthetic Gemini/ADK/Agent Platform verification; real
media and Garmin integrations remain gated.

# Agent Builder conformance

Last checked: 2026-09-03

The rules require "a functional agent — powered by Gemini and Google Cloud
Agent Builder". This records exactly which Agent Builder components this
project runs, which it does not, and where to see each in the code, so a
judge does not have to infer any of it.

## Why this document exists

The code and the earlier write-up name the runtime "Agent Platform", which is
what the SDK calls it. The rules name "Agent Builder". They are the same
suite: Google's own documentation publishes both the Agent Development Kit
and Agent Engine under `/agent-builder/`, describing Agent Builder as a suite
of products for building, scaling and governing agents in production. Nothing
had to change to satisfy the requirement — but a reader looking for the
required words would not have found them, which is a documentation failure
rather than an implementation one.

## What this project uses

| Agent Builder component | Where it runs here | Evidence in the repository |
|---|---|---|
| **Agent Development Kit (ADK)** | Builds the agent, its fixed tool, and its instruction | `app/agent_runtime/adk_agent.py` — `from google.adk.agents import Agent`, `from google.adk.models import Gemini` |
| **Agent Engine** | Hosts the deployed runtime | `app/agent_runtime/agent_platform.py` — `from vertexai import agent_engines`, `agent_engines.AdkApp(...)` |
| **Gemini** | The model behind the agent and the Story copy adapter | `Gemini(model=settings.model)`; Gemini 2.5 Flash |

Declared runtime dependencies of the deployed app, from
`app/agent_runtime/agent_platform.py`:

```
google-cloud-aiplatform[agent_engines,adk]==1.163.0
google-adk[gcp]==2.6.3
google-genai==2.17.0
```

## What this project does not use

Stated so that nothing here is read as a wider claim than it is.

- **Agent Studio / the no-code builder.** This agent is defined in code.
- **Agent Builder's search and data-store products.** This project's evidence
  comes from the rider's own GPS track and footage, not from indexed corpora.
- **Any Agent Builder feature over real ride material.** See the next section.

## The boundary this project holds

The deployed Agent Engine runtime is **synthetic-only**. It was created and
verified once, on 2026-08-17, in `asia-northeast1`, using fixed synthetic
events: the verification recorded that the fixed tool was called and a final
response returned, and nothing else. No GPX, no video, no coordinate, and no
capture time has ever been sent to it.

That is a deliberate product property, not an incidental gap. Ride footage
contains other people — their faces, their number plates, their houses — and
the local pipeline is built so the material that proves the story never has to
leave the rider's machine. The measured cost of holding that line is nil: of
68.1 GiB of source video in one real ride, 219 MiB ever reaches the screen,
and the decision about which 219 MiB is made from a 2.56 MiB GPS track and
video metadata alone. See [`../cloud-architecture-ja.md`](../cloud-architecture-ja.md).

## How to verify each claim

| Claim | How to check it |
|---|---|
| ADK builds the agent | Read `app/agent_runtime/adk_agent.py`; run `pytest tests/test_adk_agent.py` |
| Agent Engine hosts it | Read `app/agent_runtime/agent_platform.py`; run `pytest tests/test_agent_platform.py` |
| Gemini is the model | `Gemini(model=settings.model)` in `adk_agent.py` |
| The runtime is synthetic-only | `app/deployable_agent.py` takes no private input; the deployment function reads no GPX, video, or `.env` value |
| Real material stays local | `pytest tests/test_private_journey_film.py` — every result asserts `external_data_sent: false` |

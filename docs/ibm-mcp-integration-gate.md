# IBM development evidence and Partner-track gate

## Why this gate exists

Earlier planning used a rule snapshot that described Gemini plus Google Cloud
agent technology and a selected Partner product or MCP server. It also described
the IBM track in terms of using IBM Bob during development. That interpretation
is retained as historical context only: the dedicated Devpost workflow state is
not initialized in this project, so the current official wording, dates, Partner
list, and submission obligations have not yet been re-verified.

Ride Storyteller does have retained evidence that IBM Bob reviewed the codebase.
It also has a local Gemini + Google ADK synthetic path and one verified
synthetic-only Agent Platform Runtime in Tokyo. Those are technical facts, but
they do not by themselves prove current track eligibility or submission
readiness.

## What this means for Ride Storyteller

- No IBM MCP server will be added merely to satisfy an unverified assumption.
- Box remains an optional media-storage/search integration. It is not one of the
  currently verified IBM evidence and must not be relabeled as an IBM service.
- Gemini, Google ADK, and the Agent Platform Runtime are implemented and
  synthetic-call evidence is retained. Exact Agent Builder wording remains an
  official-rule verification item.
- Retain the IBM Bob before-and-after evidence and obtain a sanitized screenshot.
- Do not claim that a README mention, local mock, configuration presence, Bob
  review, or hosted synthetic call satisfies a track condition until the current
  rules and submission form are checked together.

## Optional future MCP assessment

### IBM Documentation MCP Server

This endpoint could be technically validated from a future Google MCP client, but
it is not needed for the current IBM-track path. Documentation search alone would
not materially improve the video-story workflow, so do not add it unless a
user-facing workflow need emerges.

### watsonx Orchestrate ADK MCP Server

This can expose tooling around watsonx Orchestrate resources. It requires a
separate watsonx Orchestrate environment and an explicit security review,
particularly if file access is enabled. It is not configured in this repository.

## Required decision before submission

Before submission, initialize the authenticated Devpost workflow, review the
current official rules, and make the IBM development evidence clear in the demo
and repository. If the current wording requires an IBM runtime service in
addition to Bob development use, choose one that improves the workflow and then
confirm its endpoint, authentication method, tools, data boundary, cost, and
licensing:

1. A production-workflow integration that contributes to the edit/approval flow.
2. An IBM MCP tool with a direct filmmaking or media-workflow benefit.
3. Written clarification from the hackathon organizers about an acceptable IBM
   MCP role for the IBM track.

The existing hosted synthetic Runtime proves a deployed Agent Platform call with
tool use and a final response. It still does not prove real-video analysis,
current Agent Builder wording, final Partner integration, or track compliance.

See `docs/submission/ibm-bob-evidence.md` for the retained finding-to-fix index.

## Links to re-check in the authenticated rule review

- [Agentic Cinema Official Rules](https://agentic-cinema.devpost.com/rules)
- [Google CX Agent Studio MCP tools](https://docs.cloud.google.com/gemini-enterprise-cx/cx-agent-studio/tool/mcp)
- [IBM Orchestrate Documentation MCP Server](https://developer.watson-orchestrate.ibm.com/mcp_server/wxOmcp_docs_server)
- [IBM Orchestrate ADK MCP configuration](https://developer.watson-orchestrate.ibm.com/mcp_server/wxOmcp_configuration)

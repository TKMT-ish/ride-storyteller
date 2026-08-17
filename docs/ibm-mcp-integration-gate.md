# IBM development evidence and Partner-track gate

## Official rule result

On 2026-08-17, the authenticated Devpost workflow returned the live overview,
legal terms, dates, judging criteria, prizes, announcements, registration form,
and submission requirements for **Agentic Cinema: The Blockbuster Hackathon**.
The detailed Partner wording is now verified.

The five tracks are IBM, Grafana, Parallel, ClickHouse, and Replit. The
IBM-specific rule requires the project to be built using IBM Bob during the
development process and says entries without demonstrable Bob usage do not
qualify. Confluent is optional. Box is not a Partner track.

Ride Storyteller has retained evidence that IBM Bob reviewed the codebase and
that its findings drove later implementation and tests. It also has a local
Gemini + Google ADK synthetic path, a verified synthetic-only Agent Platform
Runtime in Tokyo, and a private Cloud Run public-safe demo revision. Those facts
provide the technical basis for an IBM-track submission, but registration,
explicit eligibility/rules agreement, final track selection, and a sanitized
product-identifying Bob screenshot are still pending.

## Current decision

- IBM is the lowest-change working path because Bob already materially
  influenced the implementation. The user must still confirm the track in the
  Devpost form.
- No IBM MCP server will be added merely to satisfy a historical assumption.
- Box remains optional media-storage/search infrastructure and must not be
  relabeled as IBM or as a submission track.
- Gemini, Google ADK, and the Agent Platform Runtime are implemented and
  synthetic-call evidence is retained. The rules name Google Cloud Agent
  Builder; the current `AdkApp`/Agent Platform path must be described precisely
  and must not be relabeled as a different product.
- Bob evidence is development-process proof specific to the IBM rule. It is not
  proof of real-video analysis, public hosting, or a finished submission.

## Clause ambiguity to preserve

The general submission clause asks for Google Cloud and Partner services to be
visible in code at runtime. The IBM-specific accepted-technology clause instead
defines the mandatory IBM use as Bob during development and makes Confluent
optional. The final submission should show Bob prominently. If the Devpost
validator asks for an IBM runtime import, obtain written organizer clarification
before adding a service that does not improve the product.

## Optional future IBM services

### IBM Documentation MCP Server

Documentation search alone would not materially improve the video-story
workflow. Do not add it solely as a compliance decoration.

### watsonx Orchestrate ADK MCP Server

This would require a separate watsonx Orchestrate environment and an explicit
security, cost, authentication, and data-boundary review. It is not configured
in this repository.

## Required decisions before submission

1. The user supplies the required registration answers and explicitly confirms
   eligibility and official-rules agreement.
2. The user confirms IBM as the final track.
3. Capture a sanitized Bob screen showing both the IBM Bob identity and a
   Ride Storyteller-specific finding, with no email, key, token, cloud resource,
   private path, GPX data, or video filename.
4. Select an OSI-approved repository license.
5. Approve and verify the public repository, public hosted demo, and video.

The existing hosted synthetic Runtime proves a deployed Agent Platform call
with tool use and a final response. It still does not prove real-video analysis,
public access, registration, or final submission readiness.

See `docs/submission/ibm-bob-evidence.md`,
`docs/submission/ibm-bob-review-sanitized.md`, and
`docs/submission/official-rules-audit.md`.

## References

- [Agentic Cinema Official Rules](https://agentic-cinema.devpost.com/rules)
- [IBM Orchestrate Documentation MCP Server](https://developer.watson-orchestrate.ibm.com/mcp_server/wxOmcp_docs_server)
- [IBM Orchestrate ADK MCP configuration](https://developer.watson-orchestrate.ibm.com/mcp_server/wxOmcp_configuration)

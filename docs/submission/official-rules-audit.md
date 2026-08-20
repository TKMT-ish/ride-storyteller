# Official Agentic Cinema rules audit

> Verified through the authenticated Devpost workflow on 2026-08-20. This is a
> working compliance record, not a substitute for the official rules.

## Live refresh on 2026-08-20

The authenticated Devpost surfaces were refreshed at approximately 10:01 UTC:

- submissions remain open;
- the dates endpoint ends submissions at 2026-09-09 21:00 UTC;
- the legal terms now also end the Contest Period on September 9, 2026 at
  2:00 PM Pacific Time;
- the earlier two-day discrepancy is resolved;
- eligibility, deliverables, judging criteria, and the IBM Bob requirement are
  unchanged from the rules presented for acknowledgment;
- recent announcements cover Partner build sessions and do not announce another
  deadline change.

The IBM evidence strategy remains unchanged. The current official deadline is
2026-09-10 06:00 JST.

## Historical refresh on 2026-08-17 (superseded)

The authenticated Devpost surfaces were refreshed at approximately 13:40 UTC:

- submissions remain open;
- the dates endpoint still ends submissions at 2026-09-09 21:00 UTC;
- the legal terms still state September 7, 2026 at 2:00 PM Pacific Time;
- no retrieved announcement changes or reconciles that deadline;
- registration is available, but this participant is not registered;
- the latest announcement promotes an IBM Bob live build session and describes
  Bob as an AI coding teammate for generating, documenting, and refining code.

The earlier-deadline policy was appropriate for that snapshot, but it was
superseded when the legal terms changed to September 9. The IBM evidence
strategy remains current.

## Current official deadline

The authenticated dates endpoint and the legal terms now agree: submissions
end **September 9, 2026 at 2:00 PM Pacific Time**, which is
**2026-09-10 06:00 JST**. Final publication and submission validation should be
scheduled at least 24 hours earlier rather than relying on the closing hour.

## Required project shape

- Build a functional, production-ready agent or multi-agent system for a media
  or entertainment workflow.
- Use Gemini and Google Cloud Agent Builder.
- Enter exactly one Partner track: IBM, Grafana, Parallel, ClickHouse, or Replit.
- The project must have been created during the Contest Period. The repository's
  first commit is dated 2026-08-17, within the stated period.
- The hosted project must operate as shown in the submitted video and description.

Box is not one of the five Partner tracks. It may remain optional media
infrastructure, but it cannot be used as the submission-track credential.

## IBM track requirement

The IBM-specific rule says the project must be built using **IBM Bob as part of
the development process**. It also says that projects which do not demonstrate
IBM Bob usage are ineligible for the IBM track. Confluent is optional, although
the rule encourages it for real-time/event-driven workflows.

Ride Storyteller has an IBM Bob review transcript and a finding-to-fix evidence
index. A sanitized product-identifying screenshot still needs to be captured.
The general submission text asks for Google Cloud and Partner services to be
visible in code at runtime, while the IBM-specific accepted-technology text
defines Bob as a development-process requirement. Because those clauses are not
worded identically, the final submission should show Bob evidence prominently
and seek organizer clarification if the Devpost validator asks for an IBM
runtime import.

## Submission deliverables

- a hosted project URL for judging and testing;
- a public three-minute demonstration video on YouTube or Vimeo;
- an English video, or complete English subtitles;
- a public GitHub, GitLab, or Bitbucket repository containing all required
  source, public assets, and run instructions;
- an OSI-approved open-source license detectable at the repository root/About
  area;
- actual Google Cloud usage in code, not only a README mention;
- chosen-Partner evidence meeting the selected track's specific rule;
- the completed Devpost project form.

The video must show the project functioning and should not be only a cinematic
trailer. The public repository must never contain private GPX, GoPro footage,
credentials, local environment files, or private filesystem paths.

## Judging criteria

Each criterion is scored on a five-point scale:

1. Technological Implementation
2. Design
3. Potential Impact
4. Quality of the Idea

## Registration and eligibility gates

Registration is still incomplete. The user must personally provide the required
profile answers and explicitly agree that they meet the age, territory, export,
employment/conflict, and official-rules conditions. Codex must not infer those
answers or agreement.

The live registration form currently requires one of `Working solo`, `Looking
for teammates`, or `Already have a team`; Company Name; Job Title; self-assessed
AI experience; self-assessed Google Cloud Agent Builder experience; and one or
more primary goals. The exact options and a one-message answer template are kept
in `devpost-registration-worksheet-ja.md`.

## Official references

- [Hackathon overview](https://agentic-cinema.devpost.com/)
- [Official rules](https://agentic-cinema.devpost.com/rules)
- [Devpost terms](https://info.devpost.com/terms)

# Ride Storyteller licensing

## Selected license

Ride Storyteller uses **GNU Affero General Public License version 3 only**
(`AGPL-3.0-only`) for original source code and original text documentation,
unless a file or directory explicitly states otherwise. The complete canonical
license text is in the repository-root `LICENSE` file.

Copyright (C) 2026 Ride Storyteller contributors.

AGPL permits commercial use. It is a strong copyleft license: distribution of a
covered modified work remains subject to AGPL, and section 13 requires a
modified version used through a network to offer its Corresponding Source to
its remote users.

## Scope and exclusions

- Third-party packages retain their own licenses and copyright notices.
- `docs/submission/assets/` contains evidentiary screenshots. They may be viewed
  for project evaluation, but are not licensed for independent reuse under
  AGPL unless an individual asset says otherwise.
- Real GPX/FIT/TCX logs, GoPro video, proxy media, music, credentials, private
  catalogs, and private output are not included in the public repository and
  are not licensed by this repository.
- The software license does not grant permission to use the Ride Storyteller
  name or logo in a way that suggests endorsement or an official version.

## Direct dependency review

The installed direct dependencies were inspected locally on 2026-08-24:

- Google ADK, Google Cloud AI Platform, and Google Gen AI: Apache License 2.0.
- Gunicorn, pytest, and Ruff: MIT-family licenses.

No blocking conflict was identified at the direct-dependency level. This is a
technical inventory, not legal advice or an exhaustive transitive-dependency
audit. Dependency licenses remain separate from the Ride Storyteller license.

## Publication requirements

Before making the application publicly reachable:

1. Publish the complete corresponding source at the approved public repository.
2. Add a visible **Source** link from the public network interface to that exact
   repository/version.
3. Keep the complete `LICENSE` file at the repository root and verify that the
   hosting service detects it as AGPL-3.0.
4. Re-run the private-file, secret, license, dependency, and submission checks.

The current hosted demo remains private, so the public source-link gate is not
yet complete.

## Commercial strategy boundary

AGPL does not prohibit commercial use. Possible future revenue paths include a
managed hosted service, paid processing/support, customization, and a separate
commercial license for customers that do not want AGPL obligations. A dual-
license offering is not active. Before accepting outside code contributions or
offering another license, confirm that the project holds the necessary rights
to every affected contribution.

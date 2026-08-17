"""Video analysis is a tool boundary, not a second free-form agent.

The stable analyzer contract lives in :mod:`app.video.gemini_client`; the
Vertex AI implementation lives in :mod:`app.video.vertex_transport`. Keeping
that work outside the Story Agent makes evidence parsing deterministic and
prevents this module from becoming an untracked second decision path.
"""

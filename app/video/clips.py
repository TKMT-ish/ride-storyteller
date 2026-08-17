"""Clip operations intentionally remain split across explicit safe layers.

Timestamp resolution lives in :mod:`app.video.catalog`, evidence state lives in
:mod:`app.edit.candidate_planner`, and inspectable non-executing FFmpeg planning
lives in :mod:`app.edit.render_plan`. There is no implicit clip-cutting side
effect in this module.
"""

"""BBLOTTO FastAPI application bootstrap.

Feature endpoints are collected with FastAPI ``APIRouter`` instances while
legacy feature sections continue to share one runtime namespace.  This keeps
existing endpoint behaviour and late-bound engine overrides intact, but moves
route registration to the standard ``include_router`` mechanism.
"""
from pathlib import Path

_CORE_PART = "00_core.py"
_FEATURE_PARTS = (
    ("10_system_status_ui.py", "system-ui"),
    ("20_auth_admin_settings.py", "auth-admin-settings"),
    ("30_members.py", "members"),
    ("40_recommendations_sms.py", "recommendations-sms"),
    ("50_winning_draws_stats.py", "winning-stats"),
    ("60_exports.py", "exports"),
    ("70_ai_engine.py", "ai-engine"),
    ("75_backtest.py", "backtest"),
    ("76_member_analysis.py", "member-analysis"),
    ("77_ai_lab_core.py", "ai-lab-core"),
    ("80_dashboards_operations.py", "dashboards-operations"),
    ("90_release_rc3.py", "release-rc3"),
    ("95_engine_runtime.py", "engine-runtime"),
)

_parts_dir = Path(__file__).with_name("app_parts")
_core_path = _parts_dir / _CORE_PART
exec(compile(_core_path.read_text(encoding="utf-8"), str(_core_path), "exec"), globals(), globals())

from fastapi import APIRouter

for _part_name, _router_tag in _FEATURE_PARTS:
    router = APIRouter(tags=[_router_tag])
    _part_path = _parts_dir / _part_name
    exec(compile(_part_path.read_text(encoding="utf-8"), str(_part_path), "exec"), globals(), globals())
    app.include_router(router)

del router, _part_name, _router_tag, _part_path, _core_path, _parts_dir

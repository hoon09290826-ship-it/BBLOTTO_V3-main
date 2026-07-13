"""BBLOTTO FastAPI application bootstrap.

The former 7,985-line module is split into ordered feature sections under
``backend/app_parts``.  Sections are executed in one shared application
namespace to preserve the existing API, initialization order, and runtime
behaviour while making each feature area independently reviewable.
"""
from pathlib import Path

_PARTS = (
    "00_core.py",
    "10_system_status_ui.py",
    "20_auth_admin_settings.py",
    "30_members.py",
    "40_recommendations_sms.py",
    "50_winning_draws_stats.py",
    "60_exports.py",
    "70_ai_engine.py",
    "80_dashboards_operations.py",
    "90_release_rc3.py",
    "95_engine_upgrades.py",
    "97_rc7_exports.py",
    "99_final_overrides.py",
)

_parts_dir = Path(__file__).with_name("app_parts")
for _part_name in _PARTS:
    _part_path = _parts_dir / _part_name
    exec(compile(_part_path.read_text(encoding="utf-8"), str(_part_path), "exec"), globals(), globals())

del _part_name, _part_path, _parts_dir

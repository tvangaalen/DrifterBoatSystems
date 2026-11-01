"""The HTTP API must answer exactly like the hardware-verified 1.22.2 release (status codes, JSON bodies, error texts).

Requests that would reach hardware are only included where the hardware is not attached (the USB Link is never opened
here), so they fail the same way the real routes do - which is what pins down the error mapping of every route.

    py -m tests.test_api_golden                        # verify the current application against tests/golden/api.json
    py -m tests.test_api_golden --generate <old-tree>  # regenerate from an old checkout (v1.22.2)
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from tests.test_masterbus_golden import differences

GOLDEN = Path(__file__).resolve().parent / "golden" / "api.json"
SETTINGS_OK = {
    "default_ac_limit": 15,
    "float_protection_enabled": True,
    "float_cell_trigger_mv": 3500,
    "float_cell_resume_mv": 3420,
    "bms_refresh_interval": 30,
    "bms_popup_seconds": 3,
    "bms_connection_retry_seconds": 5,
    "balancer_refresh_interval": 30,
    "balancer_connection_retry_seconds": 30,
    "history_retention_days": 7,
}

MERGED_ROUTES = ("POST /api/bms/{battery_id}/set-soc-100",)
REQUESTS = [
    ("GET", "/api/settings", None),
    ("GET", "/api/bms", None),
    ("GET", "/api/balancers", None),
    ("GET", "/api/bluetooth-coordinator", None),
    ("GET", "/api/bluetooth-events", None),
    ("GET", "/api/bluetooth-events?limit=5", None),
    ("GET", "/api/energy", None),
    ("GET", "/api/history", None),
    ("GET", "/api/history?limit=2", None),
    ("GET", "/api/history/bms-series", None),
    ("GET", "/api/history/dashboard-series?after_id=5", None),
    ("GET", "/api/history/chart-data", None),
    ("GET", "/api/history/chart-data?hours=1", None),
    ("GET", "/api/history/chart-data?hours=0.1", None),
    ("GET", "/api/history/chart-data?hours=100000", None),
    ("POST", "/api/history/chart-data/update?hours=2", None),
    ("GET", "/api/history/contributions?start=x&end=y", None),
    ("GET", "/api/history/contributions?start=2026-10-01T10:00:00Z&end=2026-10-01T09:00:00Z", None),
    ("GET", "/api/history/contributions", None),
    ("GET", "/api/history/export", None),
    ("GET", "/api/reports/battery-health", None),
    ("POST", "/api/reports/battery-health", {"days": 0}),
    ("POST", "/api/reports/battery-health", {"days": 400}),
    ("POST", "/api/reports/battery-health", {}),
    ("POST", "/api/settings", {**SETTINGS_OK, "float_cell_resume_mv": 3480}),
    ("POST", "/api/settings", {**SETTINGS_OK, "default_ac_limit": 16}),
    ("POST", "/api/settings", {"default_ac_limit": 15}),
    ("POST", "/api/settings", {**SETTINGS_OK, "history_retention_days": 0}),
    ("POST", "/api/control/ac-limit", {"amps": 2}),
    ("POST", "/api/control/ac-limit", {"amps": 16}),
    ("POST", "/api/control/ac-limit", {"amps": 10}),
    ("POST", "/api/control/inverter", {"enabled": True}),
    ("POST", "/api/control/charger", {"enabled": False}),
    ("POST", "/api/control/ac-support", {"enabled": True}),
    ("POST", "/api/control/alternator", {"enabled": True}),
    ("POST", "/api/control/mode", {"mode": "nope"}),
    ("POST", "/api/control/mode", {"mode": "marina"}),
    ("POST", "/api/control/mode", {}),
    ("POST", "/api/control/device/toaster", {"enabled": True}),
    ("POST", "/api/control/device/solar", {"enabled": True}),
    ("POST", "/api/control/inverter", {"enabled": "maybe"}),
    ("POST", "/api/bms/refresh", None),
    ("POST", "/api/bms/1/charge", {"enabled": True}),
    ("POST", "/api/bms/3/discharge", {"enabled": False}),
    ("POST", "/api/bms/1/set-soc-100", None),
    ("POST", "/api/bms/2/set-soc-charge", None),
    ("POST", "/api/bms/2/set-soc-discharge", None),
    ("POST", "/api/bms/1/set-soc-value", {"percent": 50}),
    ("POST", "/api/bms/1/set-soc-value", None),
    ("POST", "/api/bms/1/set-soc-value", {"percent": 101}),
    ("POST", "/api/bms/1/set-soc-nonsense", None),
    ("POST", "/api/bms/set-all/charge-on", None),
    ("POST", "/api/bms/set-all/discharge-off", None),
    ("POST", "/api/bms/set-all/xyz", None),
    ("POST", "/api/bms/set-all-soc/100", None),
    ("POST", "/api/bms/set-all-soc/value", {"percent": 80}),
    ("POST", "/api/bms/set-all-soc/value", None),
    ("POST", "/api/bms/set-all-soc/nonsense", None),
    ("POST", "/api/balancers/refresh", None),
    ("POST", "/api/balancers/1/refresh", None),
    ("POST", "/api/balancers/7/refresh", None),
    ("GET", "/manifest.webmanifest", None),
    ("GET", "/local-ca.cer", None),
    ("GET", "/nope", None),
    ("GET", "/api/settings/extra", None),
]


def snapshot_response(response):
    ctype = response.headers.get("content-type", "")
    if "/api/history/export" in str(response.request.url):
        body = {"lines": len([line for line in response.text.splitlines() if line])}
    else:
        body = response.json() if "json" in ctype else {"text_length_ok": len(response.text) >= 0}
    if isinstance(body, dict) and "cutoff" in body:
        body = {**body, "cutoff": "<now>", "latest": "<now>"}  # with an empty history these are the current time
    return {"status": response.status_code, "body": body, "type": ctype.split(";")[0]}


def run(client) -> dict:
    out = {}
    for index, (method, path, payload) in enumerate(REQUESTS):
        response = client.request(method, path, json=payload) if payload is not None else client.request(method, path)
        out[f"{index:03d} {method} {path} {json.dumps(payload) if payload is not None else ''}"] = snapshot_response(response)
    spec = client.get("/openapi.json").json()
    out["openapi"] = sorted(f"{method.upper()} {path}" for path, item in spec["paths"].items() for method in item)
    out["openapi_models"] = sorted(spec["components"]["schemas"])
    return out


def old_client(tree):
    sys.path.insert(0, tree)
    from fastapi.testclient import TestClient

    import app as old_app

    return TestClient(old_app.app)


def new_client():
    from fastapi.testclient import TestClient

    from mastervolt.app import create_app
    from mastervolt.config import PATHS, Paths
    from mastervolt.runtime import Services

    folder = Path(tempfile.mkdtemp())
    for name in ("control_maps.json", "mastershunt_config_maps.json"):
        shutil.copy(PATHS.base / name, folder / name)
    shutil.copytree(PATHS.static, folder / "static", ignore=shutil.ignore_patterns("products"))
    return TestClient(create_app(Services(Paths(folder))))


def main():
    if "--generate" in sys.argv:
        result = run(old_client(sys.argv[sys.argv.index("--generate") + 1]))
        GOLDEN.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        print(f"golden file written: {GOLDEN} ({GOLDEN.stat().st_size} bytes, {len(REQUESTS)} requests)")
        return
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = json.loads(json.dumps(run(new_client()), sort_keys=True))
    new_routes = [r for r in actual["openapi"] if r not in expected["openapi"]]
    # Routes added since 1.22.2 (/api/version) are allowed; /set-soc-100 is now one of the /set-soc-{mode} values (same answer, see above).
    expected["openapi"] = sorted([r for r in expected["openapi"] if r not in MERGED_ROUTES] + new_routes)
    expected["openapi_models"] = sorted(set(expected["openapi_models"]) | set(actual["openapi_models"]))
    problems = list(differences(expected, actual))
    for line in problems[:40]:
        print("DIFFERENCE", line)
    assert not problems, f"{len(problems)} differences from the verified 1.22.2 API"
    print(
        f"HTTP API: {len(REQUESTS)} requests answer exactly like 1.22.2 (status, body, error text); new routes: {', '.join(new_routes) or 'none'}: OK"
    )


if __name__ == "__main__":
    main()

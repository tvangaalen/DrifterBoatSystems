"""viomi_config.json in <DRIFTER_DATA>\\washer (next to the code without DRIFTER_DATA). A problem with it is not fatal:
the diagnostics report it and every command answers that the washer is not set up."""
from __future__ import annotations

import json, os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_IP = "192.0.2.10"           # documentation address: nothing answers there


class WasherConfig(BaseModel):
    """The schema of viomi_config.json. Unknown keys are ignored (allowed_hosts of 3.x is no longer needed)."""
    model_config = ConfigDict(extra="ignore")
    washer_ip: str = Field(DEFAULT_IP, description="the washer's IPv4 address on the boat LAN")
    token: str | None = Field(None, description="the 32-character MIoT token (never logged or exported)")
    expected_pc_ip: str | None = Field(None, description="this PC's expected LAN address (a diagnostics warning when different)")


def data_dir() -> Path:
    d = os.environ.get("DRIFTER_DATA", "").strip()
    return Path(d) / "washer" if d else Path(__file__).resolve().parent.parent


def load(path: Path) -> tuple[WasherConfig, str | None]:
    """The configuration and an error text (None when fine). VIOMI_IP / VIOMI_TOKEN in the environment override it."""
    error, raw = None, {}
    try:
        if path.exists(): raw = json.loads(path.read_text(encoding="utf-8"))
        else: error = f"Configuration file not found: {path.name}"
    except Exception as exc: error = f"Configuration file error: {exc}"
    try: cfg = WasherConfig.model_validate(raw if isinstance(raw, dict) else {})
    except ValidationError as exc: cfg, error = WasherConfig(), f"Configuration file error: {exc.errors()[0]['loc'][0]}: {exc.errors()[0]['msg']}"
    overrides = {k: v for k, v in (("washer_ip", os.environ.get("VIOMI_IP")), ("token", os.environ.get("VIOMI_TOKEN"))) if v}
    return (cfg.model_copy(update=overrides) if overrides else cfg), error

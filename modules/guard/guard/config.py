"""Runtime files in <DRIFTER_DATA>\\guard (next to the code without DRIFTER_DATA): config.json (checked against the schema
below), state.json, ezviz_token.json, pushover.json, logs\\boatguard.log."""
from __future__ import annotations

import json, os, re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAC = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")


def data_dir() -> Path:
    d = os.environ.get("DRIFTER_DATA", "").strip()
    return Path(d) / "guard" if d else Path(__file__).resolve().parent.parent


class Router(BaseModel):
    host: str
    user: str = "root"
    key: str = Field(description="the SSH key file for the router (read-only command)")
    timeout_s: int = 10


class Ezviz(BaseModel):
    camera_serial: str
    region_url: str = "apiieu.ezvizlife.com"


class GuardConfig(BaseModel):
    """The schema of config.json. Unknown keys (web of 1.x) are ignored."""
    model_config = ConfigDict(extra="ignore")
    phone_macs: list[str] = Field(min_length=1, description="the phone(s) whose presence on the Wi-Fi means: on board")
    away_after_s: int = Field(300, ge=30, le=3600)
    poll_s: int = Field(30, ge=10, le=300)
    disarm_on_return: bool = True
    test_settle_s: float = 5
    router: Router
    ezviz: Ezviz
    sounds: dict[str, str] = {}
    priorities: dict[str, int] = {}
    notify_on: dict[str, bool] = {}          # a notification switched off in the app (missing = on)

    @field_validator("phone_macs")
    @classmethod
    def macs(cls, v):
        bad = [m for m in v if not MAC.match(m)]
        if bad: raise ValueError(f"not a MAC address: {', '.join(bad)}")
        return v


def load(path: Path) -> dict:
    """The configuration as a plain dict (the guard and the settings page change it), after the schema check."""
    try: raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError: raise SystemExit(f"{path} missing: copy config.example.json and fill it in")
    except ValueError as e: raise SystemExit(f"{path}: not valid JSON ({e})")
    try: return GuardConfig.model_validate(raw).model_dump()
    except ValidationError as e:
        first = e.errors()[0]; raise SystemExit(f"{path}: {'.'.join(str(x) for x in first['loc'])}: {first['msg']}")

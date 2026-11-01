"""Where the application keeps its files.

Code (static, docs, certificates, control maps) lives in the project folder. Runtime files (settings, history,
backups, logs, the MasterShunt discovery cache) live there too, unless `runtime` is set: Drifter Boat Systems sets the
environment variable DRIFTER_DATA (e.g. C:\\DrifterData) and then they live in DRIFTER_DATA\\energy, outside the code.
The `Paths` object is passed to the services so tests can point them at a temporary directory instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    base: Path
    runtime: Path | None = None  # folder for runtime files; None = the project folder (as before)

    @property
    def runtime_base(self) -> Path:
        return self.runtime or self.base

    @property
    def static(self) -> Path:
        return self.base / "static"

    @property
    def docs(self) -> Path:
        return self.base / "docs"

    @property
    def certs(self) -> Path:
        return self.base / "certs"

    @property
    def data(self) -> Path:
        return self.runtime_base / "data"

    @property
    def logs(self) -> Path:
        return self.runtime_base / "logs"

    @property
    def backups(self) -> Path:
        return self.runtime_base / "backups"

    @property
    def settings_file(self) -> Path:
        return self.runtime_base / "user_settings.json"

    @property
    def control_maps_file(self) -> Path:
        return self.base / "control_maps.json"

    @property
    def mastershunt_maps_file(self) -> Path:
        return self.runtime_base / "mastershunt_config_maps.json"

    @property
    def history_db(self) -> Path:
        return self.data / "history.sqlite3"

    @property
    def mos_encoding_file(self) -> Path:
        return self.data / "bms_mos_encoding.json"

    @property
    def bluetooth_log(self) -> Path:
        return self.logs / "bluetooth.log"


def _runtime_from_env() -> Path | None:
    data = os.environ.get("DRIFTER_DATA", "").strip()
    return Path(data) / "energy" if data else None


PATHS = Paths(Path(__file__).resolve().parents[1], _runtime_from_env())

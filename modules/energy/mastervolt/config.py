"""Where the application keeps its files.

Everything lives under one base directory (the project folder, which is also the folder the boat PC runs from). The
`Paths` object is passed to the services so tests can point them at a temporary directory instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    base: Path

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
        return self.base / "data"

    @property
    def logs(self) -> Path:
        return self.base / "logs"

    @property
    def backups(self) -> Path:
        return self.base / "backups"

    @property
    def settings_file(self) -> Path:
        return self.base / "user_settings.json"

    @property
    def control_maps_file(self) -> Path:
        return self.base / "control_maps.json"

    @property
    def mastershunt_maps_file(self) -> Path:
        return self.base / "mastershunt_config_maps.json"

    @property
    def history_db(self) -> Path:
        return self.data / "history.sqlite3"

    @property
    def mos_encoding_file(self) -> Path:
        return self.data / "bms_mos_encoding.json"

    @property
    def bluetooth_log(self) -> Path:
        return self.logs / "bluetooth.log"


PATHS = Paths(Path(__file__).resolve().parents[1])

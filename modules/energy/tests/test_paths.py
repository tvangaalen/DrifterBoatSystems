"""Non-hardware tests for mastervolt/config.py: runtime files follow DRIFTER_DATA, code files never move."""

import os
from pathlib import Path

from mastervolt import config


def main():
    base = Path("C:/code/energy")
    p = config.Paths(base)
    assert p.runtime_base == base and p.settings_file == base / "user_settings.json" and p.history_db == base / "data" / "history.sqlite3"
    print("Without a runtime folder everything stays in the project folder (as before): OK")

    r = config.Paths(base, Path("D:/data/energy"))
    runtime = {"data": r.data, "logs": r.logs, "backups": r.backups, "settings": r.settings_file, "shunt maps": r.mastershunt_maps_file,
               "history": r.history_db, "mos": r.mos_encoding_file, "ble log": r.bluetooth_log}
    for name, path in runtime.items():
        assert Path("D:/data/energy") in path.parents, name
    for name, path in {"static": r.static, "docs": r.docs, "certs": r.certs, "control maps": r.control_maps_file}.items():
        assert path.parent == base, name
    print("With a runtime folder: settings, history, backups, logs and the MasterShunt cache move; code and certificates stay: OK")

    old = os.environ.get("DRIFTER_DATA")
    try:
        os.environ["DRIFTER_DATA"] = "D:/data"
        assert config._runtime_from_env() == Path("D:/data") / "energy"
        os.environ["DRIFTER_DATA"] = "  "
        assert config._runtime_from_env() is None
        os.environ.pop("DRIFTER_DATA")
        assert config._runtime_from_env() is None
    finally:
        if old is not None:
            os.environ["DRIFTER_DATA"] = old
    print("DRIFTER_DATA selects <folder>\\energy; empty or unset means the project folder: OK")


if __name__ == "__main__":
    main()

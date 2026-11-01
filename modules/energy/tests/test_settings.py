"""Settings: validation (the messages are shown in the UI), the API model generated from the table, and loading an old
or damaged user_settings.json without losing the settings that are fine (above all the history retention)."""

import json
import tempfile
from pathlib import Path

from mastervolt import settings as st


def raises(values, partial=True):
    try:
        st.validate(values, partial=partial)
    except ValueError as exc:
        return str(exc)
    return None


def main():
    # ---- the Float cell-voltage settings
    assert raises({"float_cell_trigger_mv": 3500.0, "float_cell_resume_mv": 3420.0}) is None
    for bad in (
        {"float_cell_trigger_mv": 3000.0},
        {"float_cell_trigger_mv": 3700.0},
        {"float_cell_resume_mv": 3100.0},
        {"float_cell_resume_mv": 3700.0},
        {"float_cell_trigger_mv": 3500.0, "float_cell_resume_mv": 3480.0},
    ):
        assert raises(bad), f"expected a ValueError for {bad}"
    assert "30 mV below the trigger" in raises({"float_cell_trigger_mv": 3500.0, "float_cell_resume_mv": 3480.0})
    # the removed SOC trigger and warning duration are rejected as new input ...
    for removed in ("house_battery_soc", "bulk_resume_soc", "warning_popup_seconds"):
        assert "Unknown settings" in raises({removed: 1})
    assert raises({"history_retention_days": True}) and raises({"history_retention_days": 7.5}) and raises({"history_retention_days": 0})
    assert raises({}, partial=False) == "All settings fields are required"
    print("Settings validation (ranges, whole numbers, 30 mV gap, removed settings rejected): OK")

    # ---- the API model comes from the same table
    from mastervolt.api.settings import SettingsReq

    assert list(SettingsReq.model_fields) == [s.name for s in st.SETTINGS]
    try:
        SettingsReq(**{**st.DEFAULTS, "default_ac_limit": 16})
    except ValueError:
        pass
    else:
        raise AssertionError("the API model must enforce the same limits as the validator")

    # ---- loading
    folder = Path(tempfile.mkdtemp())
    path = folder / "user_settings.json"
    path.write_text(
        json.dumps(
            {
                "default_ac_limit": 12,
                "float_protection_enabled": True,
                "house_battery_soc": 95.0,
                "bulk_resume_soc": 90.0,
                "float_cell_trigger_mv": 3550.0,
                "float_cell_resume_mv": 3400.0,
                "warning_popup_seconds": 8,
                "bms_refresh_interval": 30,
                "bms_popup_seconds": 3,
                "bms_connection_retry_seconds": 5,
                "balancer_refresh_interval": 90,
                "balancer_connection_retry_seconds": 60,
                "history_retention_days": 31,
            }
        ),
        encoding="utf-8",
    )
    store = st.SettingsStore(path)
    values = store.get()
    assert "house_battery_soc" not in values and "warning_popup_seconds" not in values
    assert values["float_cell_trigger_mv"] == 3550.0 and values["history_retention_days"] == 31
    print("An older user_settings.json with the removed SOC trigger and warning duration still loads: OK")

    # one invalid value, or a key from a future version, must not throw away the retention period (the default is only 7 days)
    path.write_text(
        json.dumps({"history_retention_days": 31, "bms_refresh_interval": 9999, "future_option": True, "default_ac_limit": "x"}),
        encoding="utf-8",
    )
    values = st.SettingsStore(path).get()
    assert values["history_retention_days"] == 31, "a damaged entry must not reset the retention"
    assert (
        values["bms_refresh_interval"] == st.DEFAULTS["bms_refresh_interval"]
        and values["default_ac_limit"] == st.DEFAULTS["default_ac_limit"]
    )
    path.write_text("not json at all", encoding="utf-8")
    assert st.SettingsStore(path).get() == st.DEFAULTS
    path.write_text(json.dumps({"float_cell_trigger_mv": 3400.0, "float_cell_resume_mv": 3390.0}), encoding="utf-8")  # inconsistent pair
    values = st.SettingsStore(path).get()
    assert (values["float_cell_trigger_mv"], values["float_cell_resume_mv"]) == (
        st.DEFAULTS["float_cell_trigger_mv"],
        st.DEFAULTS["float_cell_resume_mv"],
    )
    print("A damaged or inconsistent settings file falls back per setting, never wholesale: OK")

    # ---- saving
    store = st.SettingsStore(folder / "saved.json")
    seen = []
    store.subscribe(seen.append)
    saved = store.update({**st.DEFAULTS, "history_retention_days": 14, "float_cell_trigger_mv": 3550, "default_ac_limit": 10.0})
    assert saved["history_retention_days"] == 14 and saved["float_cell_trigger_mv"] == 3550.0 and isinstance(saved["default_ac_limit"], int)
    assert (
        json.loads((folder / "saved.json").read_text())["history_retention_days"] == 14 and seen and seen[0]["history_retention_days"] == 14
    )
    assert st.SettingsStore(folder / "saved.json").get() == saved
    assert not (folder / "saved.tmp").exists(), "the file is written atomically"
    print("Saving settings: normalised, atomic, listeners told, survives a reload: OK")


if __name__ == "__main__":
    main()

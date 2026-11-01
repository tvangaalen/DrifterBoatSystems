"""Display names for the charger-state numbers the MasterBus devices report.

The enumerations differ per device family; every other value is shown as `Unknown (n)` rather than guessed.
"""

from __future__ import annotations


def _state_number(raw):
    if raw is None:
        return None
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError):
        return None


def _label(raw, names: dict):
    number = _state_number(raw)
    if number is None:
        return None
    return names.get(number, f"Unknown ({number})")


COMBIMASTER_STATES = {0: "Off", 1: "Bulk", 2: "Absorption", 3: "Float"}
MASS_CHARGER_STATES = {0: "Off", 2: "Bulk", 3: "Absorption", 4: "Float", 5: "Constant voltage"}
SOURCE_STATES = {0: "Off", 1: "Bulk", 2: "Absorption", 3: "Float"}
ALTERNATOR_STATES = {0: "Off", 1: "Bulk", 2: "Absorption", 3: "Float", 5: "Stopped"}


def charger_state_label(raw, family: str = "mass"):
    """CombiMaster: 0 Off, 1 Bulk, 2 Absorption, 3 Float. Mass Charger: 2 Bulk, 3 Absorption, 4 Float, 5 Constant voltage."""
    return _label(raw, COMBIMASTER_STATES if family == "combi" else MASS_CHARGER_STATES)


def source_charge_state_label(raw):
    """SCM Solar field 3 (charge state)."""
    return _label(raw, SOURCE_STATES)


def alternator_charge_state_label(raw):
    """Alpha Pro field 5 (charger state). Hardware verified: 5 = Stopped."""
    return _label(raw, ALTERNATOR_STATES)


def state_number(raw):
    """The state as a whole number, or None when it is missing or not numeric."""
    return _state_number(raw)

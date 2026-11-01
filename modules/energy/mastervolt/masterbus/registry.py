"""The MasterBus devices on this boat: their bus addresses and how many numbered fields each exposes.

Addresses are the 24-bit MasterBus device IDs that appear in the CAN identifiers. `max_index` is the highest field
number the device reports (used only by the read-only diagnostic tools to know how far to enumerate).
"""

COMBIMASTER = 0x1B7CE1  # CMR Charge house: shore power, inverter, house charger
SOLAR = 0x31B483  # SCM Solar charge controller
ALTERNATOR = 0x329B8C  # APR Alpha Pro MB alternator regulator
YANMAR = 0x3AE394  # INT Yanmar engine ECU interface
CHARGER_BOW = 0x61CA96  # MAC Mass charger, bow thruster battery
CHARGER_START = 0x63D010  # MAC Mass charger, start battery
START_SHUNT = 0x6D59B9  # MSH MasterShunt, start battery
BOW_SHUNT = 0x6D9E99  # MSH MasterShunt, bow battery
HOUSE_SHUNT = 0x6DB09B  # MSH MasterShunt, house battery

DEVICE_INFO = {
    COMBIMASTER: {"name": "CMR Charge house", "max_index": 57, "role": "charger_house"},
    SOLAR: {"name": "SCM Solar", "max_index": 20, "role": "solar"},
    ALTERNATOR: {"name": "APR Alpha Pro MB", "max_index": 49, "role": "alternator"},
    YANMAR: {"name": "INT Yanmar ECU", "max_index": 64, "role": "yanmar"},
    CHARGER_BOW: {"name": "MAC Charge bow", "max_index": 67, "role": "charger_bow"},
    CHARGER_START: {"name": "MAC Charge start", "max_index": 67, "role": "charger_start"},
    START_SHUNT: {"name": "MSH Start", "max_index": 46, "role": "start_shunt"},
    BOW_SHUNT: {"name": "MSH Bow", "max_index": 63, "role": "bow_shunt"},
    HOUSE_SHUNT: {"name": "MSH House", "max_index": 67, "role": "house_shunt"},
}

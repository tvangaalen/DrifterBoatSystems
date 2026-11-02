"""Constants of the anchor watch: timings, GPS rules, limits and the default settings (see the package doc)."""
import logging





VERSION = "2.0.0"
log = logging.getLogger("anchor")
EARTH = 6371008.8
FRESH_S = 10            # a position older than this is not used
FROZEN_S = 60           # a position that has not changed at all for this long is frozen (see module doc)
DIAG_S = 600            # how long the GPS values of a held source are recorded
HOLD_M = 10             # the Core's GPS (254) holds its fix until the boat is this far away (measured, see module doc)
HOLD_LOG_S = 3600       # "on hold" is logged at most once per this period (the hold comes and goes every few minutes)
HOLD_NEAR_M = 2         # 254's position flickering within this of its held own fix is still the hold (see module doc)
HOLD_MERGE_S = 120      # a 254 hold that resumes within this after a release is the same hold (logged as a release)
HOLD_SOON_S = 10        # 254's own fix unchanged this long: probably on hold, a live receiver goes first (see module doc)
CORE_INFO_S = 60        # the Core's uptime is read this often (GET :8080/info): a restart is logged
BOOT_JITTER_S = 120     # boot times this close are the same boot (uptime and clock are read a moment apart)
NET_SRC_BASE = 300      # network GPS senders (NMEA over the LAN, e.g. GPS2IP) are numbered from here (NMEA 2000 ends at 254)
NET_MAX_AGE_S = 30      # a network GPS sentence whose own GPS time is further off than this is not used (stored, re-sent)
NET_GPS_PORT = 10110    # the usual NMEA 0183 over IP port (default of the nmea_port setting)
NET_AWAY_M = 100        # a network GPS this far from every other active GPS is not used: the phone has left the boat?
# receivers that are slow by design get more time before they count as frozen (matched on the model name)
SLOW_GPS = {"ZG100": 100}  # B&G ZG100: a new position every ~40 s at rest, gaps up to 81 s (recordings 2026-10-27/28)
# the Core's route state, logged on every change (is arriving at a waypoint what starts the 254 hold?)
ROUTE_KEYS = {"navigation.data.254.originWaypoint": "from waypoint", "navigation.data.254.destinationWaypoint": "to waypoint",
              "navigation.data.254.entered": "arrival circle entered", "navigation.data.254.crossed": "waypoint crossed",
              "navigation.state.254.status": "navigation status"}
DEFAULT_GPS = "4,127,3,254"
TRACK_EVERY_S = 5
AIS_RANGE_M = 600
AIS_MAX_AGE_S = 900     # an AIS position older than this is not shown (local or internet)
AIS_ALARM_AGE_S = 180   # internet AIS older than this does not count for the proximity alarm

DEFAULTS = {
    "default_radius": 40.0,   # m, used when dropping without a radius
    "confirm_s": 10,          # boat must stay outside the circle this long before the drag alarm
    "gps_timeout_s": 30,      # no usable position for this long -> GPS alarm
    "core_timeout_s": 30,     # sensor stream down for this long -> Core alarm
    "min_depth": 0.0,         # m water depth, 0 = off
    "max_wind_kn": 0.0,       # true wind speed, 0 = off
    "bow_offset": 0.0,        # m from GPS antenna forward to the bow roller
    "gps_sources": DEFAULT_GPS,  # GNSS sources in order of preference; 254 = the Orca Core's own GPS
    "own_mmsi": "",           # "My MMSI": this boat's AIS, never shown as a target; empty = hide any target within 10 m of our GPS
    "pc_sound": True,         # beep on this PC while an alarm sounds
    "push_alerts": True,      # send alarms to the phone through Pushover (needs pushover.json)
    "alive_minutes": 60.0,    # still-alive check: alert from outside after this long without a sign of life, 0 = off
    "internet_ais": True,     # add AIS targets from aisstream.io (needs aisstream.json); the local receiver always wins
    "nfl_tracking": True,     # send the track to noforeignland.com (needs nfl.json)
    "nfl_on_anchor": True,    # send the track to noforeignland.com as soon as the anchor drops (also with nfl_tracking off)
    "track_hours": 24,
    "bow_height": 1.2,        # m from the waterline to the bow roller, for the chain advice
    "chain_formula": "5*(D+B)",  # recommended chain; D = max depth next 24 h, B = bow height, LOA (see ChainFormula)
    "loa": 0.0,               # m, length over all, for chain formulas that use LOA
    "min_ais_dist": 0.0,      # m, alarm when an AIS target comes closer than this while anchored, 0 = off
    "pos_format": "dmm",      # position tile: "dmm" degrees + decimal minutes, "dms" degrees/minutes/seconds, "dd" decimal
    "draught": 0.0,           # m, keel below the waterline; 0 = off. Shows the clearance under the keel
    "transducer_depth": 0.0,  # m, transducer below the waterline, used when the sounder does not report it
    "nmea_port": NET_GPS_PORT,  # network GPS (NMEA over UDP and TCP, e.g. GPS2IP) listens on this port
}
SETTING_LIMITS = {"default_radius": (5, 2000), "confirm_s": (0, 600), "gps_timeout_s": (5, 600), "core_timeout_s": (5, 600),
                  "min_depth": (0, 500), "max_wind_kn": (0, 150), "bow_offset": (-50, 50), "track_hours": (1, 72),
                  "alive_minutes": (0, 1440), "bow_height": (0, 10), "loa": (0, 100), "min_ais_dist": (0, 2000),
                  "draught": (0, 10), "transducer_depth": (0, 5), "nmea_port": (1024, 65535)}

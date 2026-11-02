"""1.17's module name, kept so that test_anchor_watch.py runs unchanged against the package anchor/ (2.0): every name is
re-exported from there, and the modules the tests patch through this name (time, urllib, websockets, asyncio) are the
same module objects. The anchor watch runs as `python -m anchor`."""
import asyncio, json, time, urllib.error, urllib.parse, urllib.request  # noqa: F401  (patched by the tests)

import websockets  # noqa: F401

import anchor  # noqa: F401  (puts the repository root and this folder on sys.path)
from anchor.ais import InternetAIS, read_ais  # noqa: F401
from anchor.alerts import Pushover, StillAlive  # noqa: F401
from anchor.chain import ChainFormula, chain_advice  # noqa: F401
from anchor.geo import dist_bearing_m, num, offset  # noqa: F401
from anchor.gps import NetGPS, position_sources, read_boat  # noqa: F401
from anchor.nfl import NoForeignLand  # noqa: F401
from anchor.settings import AIS_ALARM_AGE_S, AIS_MAX_AGE_S, AIS_RANGE_M, BOOT_JITTER_S, CORE_INFO_S, DEFAULTS, DEFAULT_GPS, DIAG_S, EARTH, FRESH_S, FROZEN_S, HOLD_LOG_S, HOLD_M, HOLD_MERGE_S, HOLD_NEAR_M, HOLD_SOON_S, NET_AWAY_M, NET_GPS_PORT, NET_MAX_AGE_S, NET_SRC_BASE, ROUTE_KEYS, SETTING_LIMITS, SLOW_GPS, TRACK_EVERY_S, VERSION, log  # noqa: F401
from anchor.tide import TideFeed, depth_window, tide_at, tide_summary  # noqa: F401
from anchor.tiles import TILE_RE, TileCache, tile_bbox_3857  # noqa: F401
from anchor.watch import AnchorWatch, _bad, _num, core_info_loop, sound_loop, watch_loop, winsound  # noqa: F401

"""Anchor watch for the Orca Core 2 (read-only on the Core), as a package since 2.0.

Anchor watch for the Orca Core 2.

Reads the Core's live sensor and AIS streams (read-only, same streams as orca_reader.py), keeps an anchor
position and swing radius, and raises alarms when the boat drags, GPS is lost, the Core stops talking, or
optional depth/wind limits are crossed. The watch runs here, not in the browser: alarms are evaluated and
(on Windows) sounded on this PC even when no page is open. Its page is the Anchor watch module of the Drifter app
(Drifter Boat Systems); since 1.17.0 this server has no page of its own, only the API (`/api/state`, `/api/track`,
`/api/command`) and the map tiles, on --web-bind (localhost on the boat). Network GPS keeps listening on --bind.

Position source: the GNSS sources are used in the order of the `gps_sources` setting, with failover. The Core's
own GPS (source 254) can be chosen too: with the rest of the NMEA 2000 network switched off it is the only one
left. It is not always trustworthy while the boat lies still: on 2026-10-12, with the other receivers on, 254 stayed
at one exact value for minutes, while on 2026-10-16 (Core alone) it kept moving although the Core flagged the boat
as stationary both times. A frozen position would hide a slow drag, so every source is checked directly: a position
that has not changed at all for FROZEN_S is treated as frozen and skipped (real receivers always jitter in the last
digit), and with no usable source left the GPS alarm goes off. Each source reports two positions: navigation.position
(used normally, about 4 per second) and navigation.gnss (the receiver's own fix, once a second). When the first one
is held but the source's own fix still changes, that fix is used instead; only when both are unchanged is the source
frozen. The Core's own GPS is the exception: it has a static hold. Recordings of 2026-10-26 show it keeps one fix
(position and own fix alike) while the boat lies still (46 min seen on 2026-10-27), and moves on as soon as the real position
is about 10 m away (every release jumped 10.0-10.1 m). While its receiver is alive (the fix time keeps advancing)
such a held 254 position is used, marked "hold": it is never more than about HOLD_M off. A live receiver is
preferred over a held 254, whatever the order, so with the instruments on the track stays smooth. While a source is held, its GPS values are written to recordings/ (local only, never committed) for analysis.
Since the recordings of 2026-10-28 the hold is detected on the Core's own fix: after each release navigation.gnss
holds again at once, while navigation.position flickers for minutes between a few values 0.1 m apart (HOLD_NEAR_M).
That flicker is still the hold, and a release that resumes within HOLD_MERGE_S belongs to the same hold.
Confirming a hold takes FROZEN_S, and on 2026-10-29 the anchor was dropped in that first minute after a release,
from a 254 fix that was 10 m behind. So a 254 whose own fix has not changed for HOLD_SOON_S (a live 254 changes it
every 1-5 s) already goes behind the live receivers; it is only logged as a hold once confirmed.
A power cycle of the Core clears the hold, and the "Core alone, no hold" observation of 2026-10-28 turned out to
follow a Core restart (uptime: booted 14:20). So the Core's boot time is read from its /info page (GET only) and
every restart goes to the log; every log line carries the Core's uptime. Does the hold stay away after a restart
until the boat has sailed and stopped again?
What starts the hold is not known yet (a power cycle of the Core clears it). The Core alone on the bus (instruments
off) showed no hold for hours on 2026-10-16 and 2026-10-28 while flagged stationary, so every line in the log lists
the other GPS receivers that are active. To find out, the Core's route state
(waypoints, arrival circle entered, waypoint crossed) is logged, and every start and end of a hold goes to
recordings/core_gps_log.jsonl together with that route state and the stationary flag. Every change of the Core's
stationary flag goes there too, with speed and hold state: does the hold start when the boat comes to rest? (After
2026-10-27 the route is ruled out: holds came and went with and without a route, never with an arrival flag set.)

A phone or tablet can be a GPS too (NetGPS): an app such as GPS2IP pushes NMEA 0183 (RMC, GGA) over the LAN to
port NET_GPS_PORT, UDP or TCP. Each sender becomes a source from NET_SRC_BASE on and gets the same frozen check as
any receiver. Because a phone can go ashore in the dinghy, a network GPS more than NET_AWAY_M from every other active
GPS is skipped ("away"); with no other GPS active it is used as it is.

State (anchor, settings, track, events) is kept in anchor_state.json so a restart does not lose the watch.

Map tiles (OpenStreetMap, OpenSeaMap seamarks, Esri satellite) are
fetched by this PC and kept in tile_cache/, so
areas viewed while online still show offline. Only tiles a page asks for are fetched; nothing is bulk-downloaded.

Modules: settings (constants), geo, gps (read_boat, NetGPS), ais, tide, chain, alerts (Pushover, StillAlive), nfl, watch
(AnchorWatch with the alarm logic in tick()), tiles, api (FastAPI, Drifter's module contract), __main__ (python -m anchor).
The code of 1.17 moved here verbatim (split by tools, not rewritten); test_anchor_watch.py runs unchanged against it
through anchor_watch.py.
"""
import sys
from pathlib import Path

_here = Path(__file__).resolve()
sys.path[:0] = [str(_here.parents[3]), str(_here.parents[1])]   # the repository root (common/) and modules/anchor (orca_reader)

from anchor.settings import VERSION  # noqa: E402,F401

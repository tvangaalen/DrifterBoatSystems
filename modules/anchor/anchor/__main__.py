"""python -m anchor: the anchor watch (read-only on the Orca Core). Started by drifterd with DRIFTER_TOKEN and the data
paths of modules.json; the API listens on 127.0.0.1 (plain HTTP, only the Drifter gateway calls it), network GPS (NMEA)
on --bind, the boat LAN address. The asyncio data loops run in the main thread, the API in its own."""
import argparse, asyncio, socket, threading
from pathlib import Path

import anchor  # noqa: F401  (first: puts the repository root and this folder on sys.path)
from common import logs, net
from common.service import start
from orca_reader import AIS_PATH, SENSORS_PATH, Store, devices_loop, stream_loop
from anchor.ais import InternetAIS
from anchor.alerts import Pushover, StillAlive
from anchor.api import create_app
from anchor.nfl import NoForeignLand
from anchor.settings import VERSION, log
from anchor.tide import TideFeed
from anchor.tiles import TileCache
from anchor.watch import AnchorWatch, core_info_loop, sound_loop, watch_loop

HERE = Path(__file__).resolve().parents[1]


def lan_address() -> str:
    """This PC's address on the default route (a UDP connect sends nothing); refused unless private (net.check_bind)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9)); return s.getsockname()[0]


def main():
    ap = argparse.ArgumentParser(prog="python -m anchor", description="Anchor watch for the Orca Core 2 (read-only on the Core)")
    ap.add_argument("--host", default="192.168.1.124", help="Orca Core address (default 192.168.1.124)")
    ap.add_argument("--bind", default="127.0.0.1", help="where network GPS (NMEA) listens: localhost, a private LAN address, "
                                                         "or 'auto' = this PC's LAN address on the default route")
    ap.add_argument("--web-bind", default="127.0.0.1", help="address for the API and map tiles (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8766, help="port for the API (default 8766)")
    ap.add_argument("--app-url", help="link in push alerts, e.g. the Drifter app's anchor page (default: this server)")
    ap.add_argument("--state", default=str(HERE / "anchor_state.json"), help="file that keeps the anchor, settings and track")
    ap.add_argument("--no-ais", action="store_true", help="do not open the AIS stream")
    ap.add_argument("--tile-cache", default=str(HERE / "tile_cache"), help="folder for cached map tiles")
    ap.add_argument("--pushover", default=str(HERE / "pushover.json"), help="Pushover keys file (see pushover.example.json)")
    ap.add_argument("--still-alive", default=str(HERE / "still_alive.json"), help="still-alive ping config (see still_alive.example.json)")
    ap.add_argument("--aisstream", default=str(HERE / "aisstream.json"), help="aisstream.io key for internet AIS (see aisstream.example.json)")
    ap.add_argument("--nfl", default=str(HERE / "nfl.json"), help="noforeignland.com boat tracking keys (see nfl.example.json)")
    ap.add_argument("--recordings", default=str(HERE / "recordings"), help="folder for the GPS diagnostics (held GPS, Core GPS log)")
    ap.add_argument("--no-nmea", action="store_true",
                    help="do not listen for network GPS (NMEA 0183 over UDP/TCP, e.g. GPS2IP); the port is a setting on the page")
    ap.add_argument("--tide-cache", default=str(HERE / "tide_cache.json"), help="local copy of the tide forecast (works offline)")
    a = ap.parse_args()
    if a.bind == "auto": a.bind = lan_address()
    net.check_bind(a.bind, "--bind"); net.check_bind(a.web_bind, "--web-bind")
    logs.setup()

    store = Store(); watch = AnchorWatch(store, a.state, diag_dir=a.recordings)
    page_url = a.app_url or f"http://{a.web_bind}:{a.port}/"
    watch.notifier = Pushover(a.pushover, page_url, on_event=lambda text, kind: watch.event(text, kind=kind))
    log.info("Push alerts: %s", "Pushover ready" if watch.notifier.configured else f"off ({Path(a.pushover).name} missing or invalid)")
    watch.alive = StillAlive(a.still_alive, lambda: watch.settings["alive_minutes"], on_event=lambda text, kind: watch.event(text, kind=kind))
    log.info("Still-alive check: %s", "ready" if watch.alive.configured else f"off ({Path(a.still_alive).name} missing or invalid)")
    def track_copy():
        with watch.lock: return [list(p) for p in watch.track]
    watch.nfl = NoForeignLand(a.nfl, track_copy, lambda: watch.settings["nfl_tracking"], sent=watch.nfl_sent,
                              on_event=lambda text, kind: watch.event(text, kind=kind))
    log.info("noforeignland.com tracking: %s", "ready" if watch.nfl.configured else f"off ({Path(a.nfl).name} missing or invalid)")
    def boat_center():
        pos = watch.boat.get("pos") or watch.anchor
        return (pos["lat"], pos["lon"]) if pos else None
    watch.netais = InternetAIS(a.aisstream, boat_center, lambda: watch.settings["internet_ais"], on_event=lambda text, kind: watch.event(text, kind=kind))
    watch.tide = TideFeed(a.tide_cache, boat_center, on_event=lambda text, kind: watch.event(text, kind=kind))
    log.info("Internet AIS: %s", "aisstream.io ready" if watch.netais.configured else f"off ({Path(a.aisstream).name} missing or invalid)")
    server = start(create_app(watch, TileCache(a.tile_cache)), a.web_bind, a.port)
    threading.Thread(target=sound_loop, args=(watch,), daemon=True).start()
    log.info("Anchor Watch %s: API http://%s:%d/, network GPS on %s (Core %s)", VERSION, a.web_bind, a.port, a.bind, a.host)

    async def run():
        tasks = [stream_loop(store, "sensors", f"ws://{a.host}:8089" + SENSORS_PATH.format(ms=1000), None), watch_loop(watch),
                 devices_loop(store, a.host), core_info_loop(watch, a.host), watch.netais.run(), watch.tide.run()]
        if not a.no_ais: tasks.append(stream_loop(store, "ais", f"ws://{a.host}:8089" + AIS_PATH, None))
        if not a.no_nmea:
            watch.nmea_on = True; tasks.append(watch.netgps.run(a.bind, lambda: int(watch.settings["nmea_port"])))
        await asyncio.gather(*tasks)
    try: asyncio.run(run())
    except KeyboardInterrupt: pass
    finally:
        server.should_exit = True; watch.save()


if __name__ == "__main__":
    main()

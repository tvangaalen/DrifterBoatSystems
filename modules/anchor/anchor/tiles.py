"""Map tiles fetched on demand and cached on this PC (no bulk downloads)."""
import math, os, re, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from anchor.settings import log


def tile_bbox_3857(z, x, y):
    """Web Mercator bounding box 'minx,miny,maxx,maxy' (metres) of slippy-map tile z/x/y."""
    half = math.pi * 6378137; size = 2 * half / 2 ** z
    return f"{x * size - half:.2f},{half - (y + 1) * size:.2f},{(x + 1) * size - half:.2f},{half - y * size:.2f}"


class TileCache:
    """Fetches map tiles on demand from fixed sources and keeps them on disk.

    A cached tile is served as is for MAX_AGE; after that it is refetched, and if that fails (no internet) the old
    copy is served anyway. Tiles the source does not have (404, common for the seamark overlay) are remembered for
    MISSING_AGE so they are not asked for again on every pan.
    """
    SOURCES = {   # layer -> (URL template, file extension, max native zoom)
        "osm": ("https://tile.openstreetmap.org/{z}/{x}/{y}.png", "png", 19),
        "seamark": ("https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png", "png", 18),
        "satellite": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "jpg", 19),
    }
    MAX_AGE, MISSING_AGE = 30 * 86400, 7 * 86400
    USER_AGENT = "OrcaCore2-AnchorWatch/1.0 (personal anchor alarm, tiles cached locally)"

    def __init__(self, folder):
        self.folder = Path(folder); self.upstream = threading.Semaphore(2)   # OSM policy: at most 2 connections
        self.offline_until = 0                                                  # skip fetching for a while after a network failure

    def get(self, layer, z, x, y):
        """Return (bytes, content type), or None when the tile is not available."""
        url, ext, maxz = self.SOURCES[layer]
        if not (0 <= z <= maxz and 0 <= x < 2 ** z and 0 <= y < 2 ** z): return None
        f = self.folder / layer / str(z) / str(x) / f"{y}.{ext}"; missing = f.with_suffix(".missing")
        ctype = "image/png" if ext == "png" else "image/jpeg"
        now = time.time()
        if f.exists() and now - f.stat().st_mtime < self.MAX_AGE: return f.read_bytes(), ctype
        if missing.exists() and now - missing.stat().st_mtime < self.MISSING_AGE: return None
        if now >= self.offline_until:
            req = urllib.request.Request(url.format(z=z, x=x, y=y, bbox=tile_bbox_3857(z, x, y)), headers={"User-Agent": self.USER_AGENT})
            try:
                with self.upstream, urllib.request.urlopen(req, timeout=8) as r: data = r.read()
                if data:
                    f.parent.mkdir(parents=True, exist_ok=True); tmp = f.with_suffix(".tmp"); tmp.write_bytes(data); os.replace(tmp, f)
                    missing.unlink(missing_ok=True); return data, ctype
            except urllib.error.HTTPError as e:
                if e.code == 404: missing.parent.mkdir(parents=True, exist_ok=True); missing.touch()
                else: log.warning("tile %s/%d/%d/%d: HTTP %s", layer, z, x, y, e.code)
            except Exception as e:
                self.offline_until = now + 30; log.info("map tiles offline (%s); using cached tiles only for 30 s", type(e).__name__)
        return (f.read_bytes(), ctype) if f.exists() else None


TILE_RE = re.compile(r"^/tiles/([a-z]+)/(\d{1,2})/(\d{1,7})/(\d{1,7})\.(?:png|jpg)$")

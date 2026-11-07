# Engine log

The API behind the **Engine log** module of the Drifter app, version `1.0.0`: diesel fuel fills (date, engine hours,
litres, amount paid, position), engine maintenance (date, engine hours, text) and the engine alarms, with create, read,
change and delete for every entry. FastAPI on `127.0.0.1:8097`, on Drifter's module contract (`common/service.py`).

| File | What |
|---|---|
| `enginelog/store.py` | the log in `<DRIFTER_DATA>\enginelog\log.json`, validated, written atomically; the fuel stats |
| `enginelog/engine.py` | live engine data and the engine hours from the Orca Core 2 (read-only, `propulsion` only); the engine alarms from the YDEN-02 |
| `enginelog/yden.py` | the YDEN-02's YD RAW stream (UDP 1456, listen only): PGN 127488/127489 decoded, with the engine's own warning lights |
| `enginelog/api.py` | the HTTP API (`GET /api/log`, `POST /api/<fuel or maintenance>[/<id>[/delete]]`, `POST /api/alarms/<id>/delete`, `POST /api/settings`) |

The position comes from the anchor watch (the page sends the boat's position with a new fill); the log stays on the boat
PC and is never committed. The Core is at `ENGINELOG_CORE` (default 192.168.1.124), the YDEN-02 at `ENGINELOG_YDEN` (default 192.168.1.110); `off`: without that one. Tests:
`.venv\Scripts\python.exe -m unittest test_enginelog` (no test reaches the Core, the YDEN or the internet).

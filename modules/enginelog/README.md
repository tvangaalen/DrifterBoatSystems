# Engine log

The API behind the **Engine log** module of the Drifter app, version `1.0.0`: diesel fuel fills (date and time, engine
hours, litres, position, country, nearest marina) and engine maintenance (date, text), with create, read, change and
delete for every entry. FastAPI on `127.0.0.1:8097`, on Drifter's module contract (`common/service.py`).

| File | What |
|---|---|
| `enginelog/store.py` | the log in `<DRIFTER_DATA>\enginelog\log.json`, validated, written atomically; the fuel stats |
| `enginelog/lookup.py` | country (Nominatim) and the nearest marina within 15 km (Overpass) for a position, on request only |
| `enginelog/api.py` | the HTTP API (`GET /api/log`, `GET /api/lookup`, `POST /api/<fuel or maintenance>[/<id>[/delete]]`) |

The position comes from the anchor watch (the page sends the boat's position with a new fill); the log stays on the boat
PC and is never committed. Tests: `.venv\Scripts\python.exe -m unittest test_enginelog` (no test reaches the internet).

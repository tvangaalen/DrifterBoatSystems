# Engine log

The API behind the **Engine log** module of the Drifter app, version `1.0.0`: diesel fuel fills (date, engine hours,
litres, amount paid, position), engine maintenance (date, engine hours, text) and the engine alarms, with create, read,
change and delete for every entry. FastAPI on `127.0.0.1:8097`, on Drifter's module contract (`common/service.py`).

| File | What |
|---|---|
| `enginelog/store.py` | the log in `<DRIFTER_DATA>\enginelog\log.json`, validated, written atomically; the fuel stats |
| `enginelog/engine.py` | live engine data from the Orca Core 2 (read-only, `propulsion` only): the engine hours and the engine alarms |
| `enginelog/api.py` | the HTTP API (`GET /api/log`, `POST /api/<fuel or maintenance>[/<id>[/delete]]`, `POST /api/alarms/<id>/delete`, `POST /api/settings`) |

The position comes from the anchor watch (the page sends the boat's position with a new fill); the log stays on the boat
PC and is never committed. The Core is at `ENGINELOG_CORE` (default 192.168.1.124; `off`: no engine data). Tests:
`.venv\Scripts\python.exe -m unittest test_enginelog` (no test reaches the Core or the internet).

"""python -m washer: the controller on http://127.0.0.1:8080 (WASHER_BIND may name another private address), with the
scheduler running. Started by drifterd, which gives it DRIFTER_DATA and DRIFTER_TOKEN."""
from washer import VERSION        # first: it puts the repository root (common/) on sys.path
from common import logs
from common.service import run
from washer.api import Controller, create_app

if __name__ == "__main__":
    logs.setup()
    c = Controller(); c.schedule.start()
    print(f"VIOMI washer controller {VERSION}: API on port 8080 for the Drifter gateway; keep it running for scheduled programs.", flush=True)
    run(create_app(c), 8080, "WASHER_BIND")

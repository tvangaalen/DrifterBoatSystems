"""python -m guard [run | login | pushover | status | arm | disarm]

    run       the service loop and the API on http://127.0.0.1:8095 (GUARD_BIND may name another private address);
              started by drifterd, which gives it DRIFTER_DATA and DRIFTER_TOKEN
    login     one-time: sign in to EZVIZ (asks the password and, if needed, the SMS/e-mail code; only the session is saved)
    pushover  one-time: Pushover keys for phone notifications (sends a test)
    status    which Wi-Fi clients the router sees and whether the phone is on board
    arm, disarm  manual test of the camera
"""
import sys, threading

from guard import VERSION, config       # first: it puts the repository root (common/) on sys.path
from common import logs
from common.service import run
from guard import router
from guard.api import create_app
from guard.camera import Camera, save_json
from guard.core import Guard, log
from guard.notify import Pushover

DATA = config.data_dir()
CONFIG, STATE, TOKEN, PUSHOVER, LOG = (DATA / "config.json", DATA / "state.json", DATA / "ezviz_token.json", DATA / "pushover.json",
                                       DATA / "logs" / "boatguard.log")


def login(cfg: dict) -> None:
    import getpass
    from pyezviz.client import EzvizClient
    from pyezviz.exceptions import EzvizAuthVerificationCode
    acct = input("EZVIZ account (e-mail or phone): ").strip()
    c = EzvizClient(acct, getpass.getpass("EZVIZ password (not saved): "), cfg["ezviz"].get("region_url", "apiieu.ezvizlife.com"))
    try: c.login()
    except EzvizAuthVerificationCode: c.login(sms_code=int(input("EZVIZ sent you a verification code. Code: ").strip()))
    save_json(TOKEN, c._token)
    serial, devs = cfg["ezviz"]["camera_serial"], c.get_device_infos()
    print(f"Signed in. Session saved to {TOKEN.name}.")
    print(f"Camera {serial} {'found' if serial in devs else 'NOT found'} on this account ({len(devs)} device(s))")
    c.close_session()


def setup_pushover() -> int:
    import getpass
    print("Pushover: your User Key is on https://pushover.net after logging in;")
    print("the API Token comes from 'Create an Application/API Token' on that page (name it BoatGuard).")
    user, token = getpass.getpass("User Key (hidden): ").strip(), getpass.getpass("API Token (hidden): ").strip()
    if not (user and token): print("Nothing saved."); return 1
    save_json(PUSHOVER, {"token": token, "user": user})
    ok = Pushover(PUSHOVER).send("BoatGuard test", "Notifications from BoatGuard are working.", wait=True)
    print("Test notification sent: check your phone." if ok else "Pushover rejected the keys or was unreachable: see logs\\boatguard.log.")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "run"
    cfg = config.load(CONFIG)
    logs.setup(log, LOG)
    if cmd == "login": login(cfg)
    elif cmd == "pushover": return setup_pushover()
    elif cmd == "status":
        try: seen = router.stations(cfg)
        except router.RouterError as e: print(f"router not readable ({e.kind}): {e.detail}"); return 1
        print(f"{len(seen)} Wi-Fi clients; phone {'ON BOARD' if seen & {m.lower() for m in cfg['phone_macs']} else 'NOT on Wi-Fi'}")
    elif cmd in ("arm", "disarm"): Camera(cfg, TOKEN).set_armed(cmd == "arm"); log.info("manual %s done", cmd)
    elif cmd == "run":
        g = Guard(cfg, Camera(cfg, TOKEN), STATE, CONFIG, notifier=Pushover(PUSHOVER))
        threading.Thread(target=g.run, daemon=True, name="guard").start()
        log.info("BoatGuard %s: API on port 8095 for the Drifter gateway", VERSION)
        run(create_app(g, LOG), 8095, "GUARD_BIND")
    else: print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

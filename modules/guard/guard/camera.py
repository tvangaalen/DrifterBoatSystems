"""Arming through the EZVIZ cloud (pyezviz), with the session saved in ezviz_token.json: the password is never stored."""
from __future__ import annotations

import json, threading
from pathlib import Path


def load_json(p: Path, default):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except FileNotFoundError: return default


def save_json(p: Path, data) -> None:
    tmp = Path(p).with_suffix(".tmp"); tmp.write_text(json.dumps(data, indent=2), encoding="utf-8"); tmp.replace(p)


class Camera:
    def __init__(self, cfg: dict, token_path: Path):
        self.cfg, self.token_path = cfg["ezviz"], Path(token_path)
        self.lock = threading.Lock()                     # one EZVIZ session refresh at a time (the refresh id rotates)

    def _client(self):
        from pyezviz.client import EzvizClient
        tok = load_json(self.token_path, None)
        if not tok: raise RuntimeError("no EZVIZ session: run `python -m guard login` first")
        c = EzvizClient(token=tok, url=self.cfg.get("region_url", "apiieu.ezvizlife.com"))
        c.login()                                        # refreshes the session from the saved refresh id; no password
        save_json(self.token_path, c._token)
        return c

    def set_armed(self, armed: bool) -> None:
        with self.lock:
            c = self._client()
            try: c.set_camera_defence(self.cfg["camera_serial"], 1 if armed else 0)
            finally: save_json(self.token_path, c._token); c.close_session()

    def status(self) -> dict:
        """What the EZVIZ cloud reports for the camera: armed (alarm_notify), battery %, online."""
        with self.lock:
            c = self._client()
            try: d = c.load_cameras()[self.cfg["camera_serial"]]
            finally: save_json(self.token_path, c._token); c.close_session()
        return {"armed": bool(d.get("alarm_notify")), "battery": d.get("battery_level"), "online": d.get("status") == 1}

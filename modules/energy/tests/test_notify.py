"""Float protection notification: on by default, sent once per Float start with priority normal, never without keys or
when switched off; the switch survives in data/notifications.json. Nothing reaches Pushover (a fake post)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mastervolt.notify import FLOAT_MESSAGE, Notifier


def main():
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "energy" / "data"
        sent = []
        n = Notifier(data, Path(tmp) / "anchor" / "pushover.json", post=sent.append)
        assert n.float_enabled() and not n.status()["pushover_configured"]
        n.float_started(wait=True)
        assert sent == [] and "not set up" in n.last_error
        (Path(tmp) / "anchor").mkdir()
        (Path(tmp) / "anchor" / "pushover.json").write_text(json.dumps({"app_token": "a" * 30, "user_key": "u" * 30}), encoding="utf-8")
        n.float_started(wait=True)
        assert len(sent) == 1 and sent[0]["message"] == FLOAT_MESSAGE and sent[0]["priority"] == 0, sent
        assert sent[0]["token"] == "a" * 30 and n.last_error is None and n.last_sent
        n.set_float_enabled(False)
        assert not Notifier(data).float_enabled()
        n.float_started(wait=True)
        assert len(sent) == 1
        n.set_float_enabled(True)
        n.float_started(wait=True)
        assert len(sent) == 2
        assert "a" * 30 not in json.dumps(n.status())
        # shore power: the first stable state is the baseline; a change counts after 30 s; a flicker and None do nothing
        sent.clear()
        for t in (0, 10, 20, 30):
            n.shore_seen(False, now=t, wait=True)
        assert sent == [] and n.status()["shore_connected"] is False
        n.shore_seen(True, now=40, wait=True); n.shore_seen(False, now=50, wait=True); n.shore_seen(None, now=60, wait=True)
        assert sent == []
        for t in (100, 110, 120, 130):
            n.shore_seen(True, now=t, wait=True)
        assert [x["message"] for x in sent] == ["Shore power ON"] and sent[0]["priority"] == 0, sent
        n.set_enabled("shore_notification", False)
        for t in (200, 240):
            n.shore_seen(False, now=t, wait=True)
        assert len(sent) == 1 and n.status()["shore_connected"] is False and n.status()["float_notification"] is True
        # priority and sound per notification (never emergency), kept next to the switches; the shared keys win
        assert n.prefs()["float"] == {"priority": 0, "sound": ""}
        n.set_prefs({"float": {"priority": 1, "sound": "tugboat"}})
        assert n.prefs()["float"] == {"priority": 1, "sound": "tugboat"} and n.prefs()["shore"]["priority"] == 0
        assert n.status()["shore_notification"] is False                     # the switches stay as they were
        for bad in ({"float": {"priority": 2}}, {"float": {"sound": "boom"}}, {"other": {}}):
            try:
                n.set_prefs(bad)
                raise AssertionError(bad)
            except ValueError:
                pass
        shared = Path(tmp) / "pushover.json"
        shared.write_text(json.dumps({"app_token": "s" * 30, "user_key": "u" * 30}), encoding="utf-8")
        n2 = Notifier(data, Path(tmp) / "anchor" / "pushover.json", post=sent.append, shared=shared)
        sent.clear()
        n2.float_started(wait=True)
        assert sent[0]["token"] == "s" * 30 and sent[0]["priority"] == 1 and sent[0]["sound"] == "tugboat", sent
    print("Float protection and shore power notifications (on by default, priority normal, switches kept, shore after 30 s): OK")


if __name__ == "__main__":
    main()

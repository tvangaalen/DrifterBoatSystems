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
    print("Float protection notification (on by default, priority normal, switch kept, never without keys): OK")


if __name__ == "__main__":
    main()

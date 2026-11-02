"""ApiContract against the Flask controller 3.8 (viomi_web_english_v58.py): the reference the FastAPI package must match.
Temporary: removed together with the Flask controller."""
import importlib, os, sys, types, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_api_contract import ApiContract, data_dir  # noqa: E402

H = {"Host": "127.0.0.1:8080", "X-Viomi-Request": "1"}


class FlaskControllerContract(ApiContract, unittest.TestCase):
    def make(self, fake, now, keep_data=False):
        self.dir = data_dir(self.dir if keep_data else None)
        os.environ["DRIFTER_DATA"] = self.dir
        import viomi_web_english_v58 as v
        v = importlib.reload(v)
        clock = {"now": now, "mono": 1000.0}   # monotonic time moves only with sleep() and tick()
        orig_init = v.initialize_device
        def init():
            orig_init(); v.DEVICE = fake                   # never a real MiotDevice in the test
        v.initialize_device = init; init()
        v.check_udp_handshake = lambda ip, timeout=2.0: True
        v._now_local = lambda: clock["now"]
        v.time = types.SimpleNamespace(sleep=lambda s: clock.__setitem__("mono", clock["mono"] + s), monotonic=lambda: clock["mono"],
                                       perf_counter=v.time.perf_counter, time=v.time.time)
        v.load_schedule()
        c = v.app.test_client()

        def get(path):
            r = c.get(path, headers=H); return r.status_code, r.get_json()

        def post(path, body=None):
            r = c.post(path, headers=H, json=body if body is not None else {}); return r.status_code, r.get_json()

        def export():
            r = c.get("/diagnostics/export", headers=H); return r.status_code, r.get_data(as_text=True), {k.lower(): val for k, val in r.headers.items()}

        def tick():
            clock["mono"] += 5; v.execute_due_schedule(); v.monitor_active_schedule()

        impl = types.SimpleNamespace(tick=tick, set_now=lambda dt: clock.__setitem__("now", dt),
                                     events=lambda: list(v.EVENT_LOG), export=export, summary=v.diagnostics_summary)
        return get, post, impl

    dir = None


if __name__ == "__main__":
    unittest.main()

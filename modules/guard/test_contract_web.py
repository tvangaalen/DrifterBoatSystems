"""ApiContract against the stdlib BoatGuard server (boatguard.py + boatguard_web.py): the reference for the FastAPI
package. Temporary: removed together with those two files."""
import http.client, importlib, json, os, sys, threading, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_api_contract import ApiContract  # noqa: E402


class StdlibContract(ApiContract, unittest.TestCase):
    def make(self, d, cam, seen, t, note):
        os.environ["DRIFTER_DATA"] = str(d.parent)
        import boatguard as B, boatguard_web as W
        B = importlib.reload(B); W = importlib.reload(W)
        cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
        g = B.Guard(cfg, cam, stations=lambda c: seen[0], clock=lambda: t[0], state_path=d / "state.json", notifier=note)
        srv = W.ThreadingHTTPServer(("127.0.0.1", 0), W.make_handler(g)); threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown); port = srv.server_address[1]

        def call(method, path, body=None, ctype="application/json"):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            data = None if body is None else body if isinstance(body, str) else json.dumps(body)
            c.request(method, path, body=data, headers={"Content-Type": ctype} if data is not None else {})
            r = c.getresponse(); raw = r.read(); c.close(); return r.status, json.loads(raw or b"{}")

        return (lambda path: call("GET", path)), (lambda path, body=None, ctype="application/json": call("POST", path, body if body is not None else {}, ctype)), g


if __name__ == "__main__":
    unittest.main()

"""ApiContract against the stdlib server of the anchor watch 1.17 (anchor_watch.make_handler): the reference for the
FastAPI package. Temporary: removed together with that server."""
import http.client, json, sys, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchor_watch as A  # noqa: E402
from test_api_contract import ApiContract  # noqa: E402


class StdlibContract(ApiContract, unittest.TestCase):
    def make(self, watch, tiles):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), A.make_handler(watch, tiles)); threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown); port = srv.server_address[1]

        def call(method, path, body=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            data = None if body is None else body if isinstance(body, str) else json.dumps(body)
            c.request(method, path, body=data, headers={"Content-Type": "application/json"} if data is not None else {})
            r = c.getresponse(); d = r.read(); c.close()
            return r.status, r.getheader("Content-Type", ""), r.getheader("Cache-Control", ""), d
        return call


if __name__ == "__main__":
    unittest.main()

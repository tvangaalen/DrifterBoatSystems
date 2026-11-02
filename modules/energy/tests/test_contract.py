"""The Drifter module contract of `python -m mastervolt` (`mastervolt/api/contract.py`): the token on every request
but /health, fail closed without a token, no-store on JSON, and the bind check. Routes that need no hardware only."""

import os
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mastervolt import __main__ as entry
from mastervolt import __version__
from mastervolt.api.contract import TOKEN_HEADER, add_contract

TOKEN = "test-token-not-secret"  # privacy: ok


def make_app(token):
    app = FastAPI()

    @app.get("/api/version")
    def version():
        return {"version": __version__}

    @app.post("/api/control/inverter")
    def control():
        raise AssertionError("must never be reached without the token")

    return add_contract(app, token)


class ContractTest(unittest.TestCase):
    def test_token_required(self):
        client = TestClient(make_app(TOKEN))
        self.assertEqual(client.get("/api/version").status_code, 403)
        self.assertEqual(client.get("/api/version", headers={TOKEN_HEADER: "wrong"}).status_code, 403)
        self.assertEqual(client.post("/api/control/inverter", json={"on": False}).status_code, 403)
        response = client.get("/api/version", headers={TOKEN_HEADER: TOKEN})
        self.assertEqual(
            (response.status_code, response.json(), response.headers["cache-control"]), (200, {"version": __version__}, "no-store")
        )

    def test_fail_closed_without_token(self):
        client = TestClient(make_app(""))
        self.assertEqual(client.get("/api/version", headers={TOKEN_HEADER: ""}).status_code, 403)
        with mock.patch.dict(os.environ, {"DRIFTER_TOKEN": ""}):
            self.assertEqual(TestClient(make_app(None)).get("/api/version").status_code, 403)

    def test_health(self):
        body = TestClient(make_app(TOKEN)).get("/health").json()
        self.assertEqual((body["ok"], body["module"], body["version"]), (True, "energy", __version__))

    def test_bind_check(self):
        for good in ("", "127.0.0.1", "localhost", "192.168.1.20", "10.0.0.5"):
            with mock.patch.dict(os.environ, {"MASTERVOLT_BIND": good}):
                self.assertTrue(entry.bind_address())
        for bad in ("0.0.0.0", "8.8.8.8", "169.254.1.1", "boat.example"):
            with mock.patch.dict(os.environ, {"MASTERVOLT_BIND": bad}):
                with self.assertRaises(SystemExit):
                    entry.bind_address()


if __name__ == "__main__":
    unittest.main()

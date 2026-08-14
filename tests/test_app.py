"""Tests for the local app server.

    ./.venv/bin/python -m unittest discover -s tests

The server holds a complete financial history behind a socket, so the access
gate gets the same scrutiny as the parsers. Every test drives a real server on
a real loopback port.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["STATEMENT_RULES"] = os.path.join(HERE, "fixtures", "rules.json")

from statementproof import app  # noqa: E402


class ServerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["STATEMENTPROOF_HOME"] = cls.tmp
        cls.httpd, cls.url = app.serve()
        cls.port = cls.httpd.socket.getsockname()[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        os.environ.pop("STATEMENTPROOF_HOME", None)

    def get(self, path, token=None, host=None, method="GET", body=None, headers=None):
        token = app.STATE.token if token is None else token
        sep = "&" if "?" in path else "?"
        url = f"http://127.0.0.1:{self.port}{path}{sep}t={token}"
        req = urllib.request.Request(url, data=body, method=method)
        if host:
            req.add_header("Host", host)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()


class TestAccessGate(ServerTestCase):
    def test_the_page_loads_with_the_token(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"statementproof", body)

    def test_no_token_is_rejected(self):
        # Another process on this machine must not be able to drive the API by
        # finding the port.
        status, _ = self.get("/", token="")
        self.assertEqual(status, 403)

    def test_a_wrong_token_is_rejected(self):
        status, _ = self.get("/", token="not-the-token")
        self.assertEqual(status, 403)

    def test_every_api_route_is_gated(self):
        for route in ("/api/state", "/api/detect", "/api/verify",
                      "/api/uncategorized", "/dashboard"):
            status, _ = self.get(route, token="wrong")
            self.assertEqual(status, 403, route)

    def test_post_routes_are_gated(self):
        for route in ("/api/label", "/api/generate", "/api/use-folder"):
            status, _ = self.get(route, token="wrong", method="POST", body=b"{}")
            self.assertEqual(status, 403, route)

    def test_a_foreign_host_header_is_rejected(self):
        # DNS-rebinding: a malicious page resolves its own name to 127.0.0.1
        # and calls us from the browser. The Host header gives it away.
        status, _ = self.get("/", host="evil.example.com")
        self.assertEqual(status, 403)

    def test_no_cors_headers_are_sent(self):
        url = f"http://127.0.0.1:{self.port}/api/state?t={app.STATE.token}"
        with urllib.request.urlopen(url, timeout=10) as r:
            self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))

    def test_token_is_long_enough_to_not_be_guessable(self):
        self.assertGreaterEqual(len(app.STATE.token), 32)


class TestBinding(unittest.TestCase):
    def test_server_binds_loopback_only(self):
        # Binding 0.0.0.0 would expose a financial history to the local network.
        httpd, _ = app.serve()
        try:
            self.assertEqual(httpd.socket.getsockname()[0], "127.0.0.1")
        finally:
            httpd.server_close()

    def test_each_session_gets_a_fresh_token(self):
        a = app.State().token
        b = app.State().token
        self.assertNotEqual(a, b)


class TestUploadSafety(ServerTestCase):
    def upload(self, name, data):
        status, body = self.get("/api/upload", method="POST", body=data,
                                headers={"X-Filename": name,
                                         "Content-Type": "application/pdf"})
        return status, json.loads(body)

    def test_a_real_pdf_is_accepted(self):
        status, r = self.upload("statement.pdf", b"%PDF-1.4\nfake body")
        self.assertEqual(status, 200)
        self.assertTrue(r["ok"], r)

    def test_a_non_pdf_is_rejected_by_content_not_extension(self):
        status, r = self.upload("evil.pdf", b"<?php system($_GET[0]); ?>")
        self.assertFalse(r["ok"])
        self.assertIn("not a PDF", r["error"])

    def test_a_traversing_filename_cannot_escape_the_library(self):
        _, r = self.upload("../../../../tmp/pwned.pdf", b"%PDF-1.4 x")
        self.assertTrue(r["ok"])
        self.assertNotIn("/", r["name"])
        self.assertNotIn("..", r["name"])
        written = os.path.join(os.environ["STATEMENTPROOF_HOME"], "statements", r["name"])
        self.assertTrue(os.path.exists(written))

    def test_uploads_do_not_overwrite_each_other(self):
        _, a = self.upload("same.pdf", b"%PDF-1.4 first")
        _, b = self.upload("same.pdf", b"%PDF-1.4 second")
        self.assertNotEqual(a["name"], b["name"])

    def test_an_oversized_body_is_refused(self):
        status, _ = self.get("/api/upload", method="POST", body=b"%PDF" + b"x" * 16,
                             headers={"Content-Length": str(app.MAX_UPLOAD + 1)})
        self.assertIn(status, (413, 400))


class TestSafeName(unittest.TestCase):
    def test_sanitizes(self):
        self.assertEqual(app.safe_name("../../etc/passwd"), "passwd.pdf")
        self.assertEqual(app.safe_name("a b.pdf"), "a_b.pdf")
        self.assertEqual(app.safe_name(""), "statement.pdf")
        self.assertEqual(app.safe_name("....pdf"), "pdf.pdf")
        self.assertTrue(app.safe_name("x" * 400).endswith(".pdf"))
        self.assertLessEqual(len(app.safe_name("x" * 400)), 124)


class TestGuardsBeforeParsing(ServerTestCase):
    def test_uncategorized_requires_verification_first(self):
        app.STATE.parsed = False
        status, body = self.get("/api/uncategorized")
        self.assertFalse(json.loads(body)["ok"])

    def test_detecting_a_missing_folder_reports_rather_than_raises(self):
        r = app.detect_source("/definitely/not/here")
        self.assertFalse(r["ok"])
        self.assertIn("not a folder", r["error"])


class TestGenerateGate(unittest.TestCase):
    """A failing check must stop generation and write nothing.

    generate() calls verify(), which re-parses from disk -- so a failure has to
    be injected at the verify boundary, not into a parsed statement, or the
    re-parse silently discards it.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["STATEMENTPROOF_HOME"] = self.tmp
        self.real_verify = app.verify

    def tearDown(self):
        app.verify = self.real_verify
        os.environ.pop("STATEMENTPROOF_HOME", None)

    def test_failing_checks_block_generation(self):
        app.verify = lambda: {
            "ok": True, "can_generate": False, "statements": [],
            "totals": {"failed_checks": 1, "unparsed": 0, "continuity_problems": 0,
                       "statements": 1, "transactions": 10},
            "accounts": [], "continuity": [],
        }
        result = app.generate()
        self.assertFalse(result["ok"])
        self.assertIn("nothing was written", result["error"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "out", "dashboard.html")))

    def test_continuity_problems_block_generation(self):
        app.verify = lambda: {
            "ok": True, "can_generate": False, "statements": [],
            "totals": {"failed_checks": 0, "unparsed": 0, "continuity_problems": 2,
                       "statements": 2, "transactions": 20},
            "accounts": [], "continuity": ["gap", "chain break"],
        }
        self.assertFalse(app.generate()["ok"])

    def test_an_unverifiable_source_blocks_generation(self):
        app.verify = lambda: {"ok": False, "error": "no supported statements found"}
        result = app.generate()
        self.assertFalse(result["ok"])


class TestRuleSuggestion(unittest.TestCase):
    def test_longest_common_substring(self):
        self.assertEqual(
            app.longest_common_substring(["AAA CORNER CAFE 123", "ZZ CORNER CAFE 999"]),
            " CORNER CAFE ")
        self.assertEqual(app.longest_common_substring([]), "")
        self.assertEqual(app.longest_common_substring(["abc", "xyz"]), "")


if __name__ == "__main__":
    unittest.main()

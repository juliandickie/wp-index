"""End-to-end test: wp_index.main() against a fake WordPress REST server.

Spins up a local HTTP server (localhost only, no external network) that mimics
the wp-json endpoints the extractor uses, runs full extractions against it,
and checks the real files written to disk. Discovered by unittest like every
other test, so CI runs it through test/smoke.test.sh unchanged.
"""
import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import wp_index  # noqa: E402


POST = {
    "id": 201,
    "slug": "scanner-review",
    "status": "publish",
    "link": "https://fake.test/scanner-review/",
    "date": "2024-05-01T10:00:00",
    "modified": "2024-06-01T10:00:00",
    "author": 7,
    "title": {"rendered": "Scanner Review &amp; Verdict"},
    "content": {"rendered": (
        "<p>Intro <strong>bold</strong>.</p>"
        "<script>track()</script>"
        "<style>.x{color:red}</style>"
        "<h2>Specs</h2>"
        "<table><tr><th>Model</th><th>Price</th></tr>"
        "<tr><td>X100</td><td>$5</td></tr></table>"
        '<p><img src="https://img.test/unit.jpg" alt="Unit"></p>'
        '<iframe src="https://www.youtube.com/embed/abc123"></iframe>'
        "<pre><code>line1\nline2</code></pre>"
        "<ul><li>one<ul><li>nested</li></ul></li></ul>"
    )},
    "excerpt": {"rendered": "<p>Our verdict.</p>"},
    "custom_field": "keepme",
    "yoast_head_json": {"description": "d" * 80},
    "_embedded": {
        "author": [{"name": "Dr Test"}],
        "wp:term": [[
            {"name": "Reviews", "taxonomy": "category"},
            {"name": "scanners", "taxonomy": "post_tag"},
        ]],
        "wp:featuredmedia": [{"source_url": "https://img.test/hero.jpg"}],
    },
}

# a hostile site returning a traversal slug; must land inside the output dir
EVIL = dict(POST, id=202, slug="../../evil",
            title={"rendered": "Evil"}, content={"rendered": "<p>owned</p>"},
            excerpt={"rendered": "<p>e</p>"}, yoast_head_json=None)

PAGE = dict(POST, id=301, slug="about",
            title={"rendered": "About"}, content={"rendered": "<p>About us.</p>"},
            excerpt={"rendered": "<p>a</p>"}, yoast_head_json=None)


class FakeWordPress(BaseHTTPRequestHandler):
    hits = {"posts": 0}

    def do_GET(self):
        path = wp_index.urllib.parse.urlparse(self.path).path.rstrip("/")
        if path == "/wp-json/wp/v2":
            return self._json({"routes": {"/wp/v2/posts": {}}})
        if path == "/wp-json/wp/v2/posts":
            type(self).hits["posts"] += 1
            return self._json([POST, EVIL], total_pages=1)
        if path == "/wp-json/wp/v2/pages":
            return self._json([PAGE], total_pages=1)
        if path == "/wp-json/wp/v2/broken":
            return self._json({"code": "internal_error"}, status=500)
        return self._json({"code": "rest_no_route"}, status=400)

    def _json(self, obj, status=200, total_pages=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if total_pages is not None:
            self.send_header("X-WP-TotalPages", str(total_pages))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep test output clean
        pass


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # urllib honours proxy env vars; make sure localhost stays direct
        os.environ.setdefault("no_proxy", "127.0.0.1,localhost")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeWordPress)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.site = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    @staticmethod
    def _read(path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _run(self, out, extra=()):
        # blank creds so a developer's shell env cannot leak auth into the run
        env = {"WP_USER": "", "WP_APP_PASSWORD": ""}
        argv = ["--site", self.site, "--out", out, "--delay", "0"] + list(extra)
        with mock.patch.dict(os.environ, env), \
             contextlib.redirect_stdout(io.StringIO()):
            return wp_index.main(argv)

    def test_full_extraction(self):
        with tempfile.TemporaryDirectory() as out:
            FakeWordPress.hits["posts"] = 0
            self.assertEqual(self._run(out, ["--type", "posts,pages"]), 0)

            post_md_path = os.path.join(out, "posts", "2024-05-01_scanner-review.md")
            self.assertTrue(os.path.isfile(post_md_path))
            # hostile slug contained inside the output directory
            self.assertTrue(os.path.isfile(os.path.join(out, "posts", "2024-05-01_evil.md")))
            self.assertTrue(os.path.isfile(os.path.join(out, "pages", "2024-05-01_about.md")))

            md = self._read(post_md_path)
            self.assertIn('title: "Scanner Review & Verdict"', md)
            self.assertIn('categories: ["Reviews"]', md)
            self.assertIn('tags: ["scanners"]', md)
            self.assertIn('featured_image: "https://img.test/hero.jpg"', md)
            self.assertIn("seo_meta_source: yoast", md)
            self.assertIn("**bold**", md)
            self.assertIn("## Specs", md)
            self.assertIn("| Model | Price |", md)
            self.assertIn("| X100 | $5 |", md)
            self.assertIn("![Unit](https://img.test/unit.jpg)", md)
            self.assertIn("[embedded content](https://www.youtube.com/embed/abc123)", md)
            self.assertIn("```\nline1\nline2\n```", md)
            self.assertIn("- one\n  - nested", md)
            self.assertNotIn("track()", md)
            self.assertNotIn("color:red", md)

            with open(os.path.join(out, "index", "posts-index.csv"), encoding="utf-8") as f:
                rows = {r["slug"]: r for r in csv.DictReader(f)}
            self.assertEqual(rows["scanner-review"]["categories"], "Reviews")
            self.assertEqual(rows["scanner-review"]["tags"], "scanners")

            archive = json.loads(self._read(os.path.join(out, "index", "archive.json")))
            raw = {i["id"]: i for i in archive["types"]["posts"]}[201]
            self.assertEqual(raw["custom_field"], "keepme")          # raw item, fields survive
            self.assertIn("track()", raw["content"]["rendered"])      # original HTML kept in archive

            kb = self._read(os.path.join(out, "index", "knowledge-base.md"))
            self.assertIn("## Scanner Review & Verdict", kb)
            self.assertIn("- Categories: Reviews", kb)

            # successful run clears checkpoints; a rerun must refetch, not reuse
            self.assertFalse(os.path.exists(os.path.join(out, ".checkpoints")))
            self.assertEqual(self._run(out, ["--type", "posts,pages"]), 0)
            self.assertEqual(FakeWordPress.hits["posts"], 2)

            # a file whose item vanished from the site is archived, not deleted
            stale = os.path.join(out, "posts", "1999-01-01_gone.md")
            open(stale, "w").close()
            self.assertEqual(self._run(out, ["--type", "posts,pages"]), 0)
            self.assertFalse(os.path.exists(stale))
            self.assertTrue(os.path.isfile(
                os.path.join(out, "orphaned", "posts", "1999-01-01_gone.md")))
            self.assertTrue(os.path.isfile(os.path.join(out, "orphaned", "README.md")))

    def test_failed_type_keeps_checkpoints_and_exits_1(self):
        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(self._run(out, ["--type", "posts,broken"]), 1)
            checkpoint = os.path.join(out, ".checkpoints", "items_posts.json")
            self.assertTrue(os.path.isfile(checkpoint))
            saved = json.loads(self._read(checkpoint))
            self.assertEqual(len(saved["items"]), 2)
            # the good type's output was still written before the failure
            self.assertTrue(os.path.isfile(
                os.path.join(out, "posts", "2024-05-01_scanner-review.md")))


if __name__ == "__main__":
    unittest.main()

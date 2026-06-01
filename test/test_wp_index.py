import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import wp_index  # noqa: E402


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(wp_index.slugify("Hello, World! A Test"), "hello-world-a-test")

    def test_empty(self):
        self.assertEqual(wp_index.slugify(""), "")

    def test_truncates(self):
        self.assertEqual(wp_index.slugify("a" * 100, max_length=10), "a" * 10)


class TestSeo(unittest.TestCase):
    def test_perfect(self):
        score, grade = wp_index.score_seo("x" * 45, "y" * 100, "z" * 20)
        self.assertEqual(score, 100)
        self.assertEqual(grade, "A")

    def test_empty(self):
        score, grade = wp_index.score_seo("", "", "")
        self.assertEqual(score, 0)
        self.assertEqual(grade, "F")

    def test_mid(self):
        # title 25 chars (+25), meta 10 chars (+20), slug 10 chars (+20) = 65 -> D
        score, grade = wp_index.score_seo("a" * 25, "b" * 10, "c" * 10)
        self.assertEqual(score, 65)
        self.assertEqual(grade, "D")


class TestStale(unittest.TestCase):
    def test_older_is_stale(self):
        self.assertTrue(wp_index.is_stale("2024-06-01T10:00:00", "2025-01-01"))

    def test_newer_is_not_stale(self):
        self.assertFalse(wp_index.is_stale("2025-06-01T10:00:00", "2025-01-01"))

    def test_no_threshold_never_stale(self):
        self.assertFalse(wp_index.is_stale("2000-01-01T00:00:00", None))


class TestHtml(unittest.TestCase):
    def test_bold_in_paragraph(self):
        self.assertEqual(
            wp_index.html_to_markdown("<p>Hello <strong>world</strong>.</p>"),
            "Hello **world**.",
        )

    def test_heading_then_paragraph(self):
        self.assertEqual(
            wp_index.html_to_markdown("<h2>Title</h2><p>Body</p>"),
            "## Title\n\nBody",
        )

    def test_link(self):
        self.assertEqual(
            wp_index.html_to_markdown("<a href='https://x.com'>link</a>"),
            "[link](https://x.com)",
        )

    def test_unordered_list(self):
        self.assertEqual(
            wp_index.html_to_markdown("<ul><li>one</li><li>two</li></ul>"),
            "- one\n- two",
        )

    def test_empty(self):
        self.assertEqual(wp_index.html_to_markdown(""), "")


class TestAuthorAndTypes(unittest.TestCase):
    def test_author_from_map(self):
        item = {"author": 7}
        self.assertEqual(wp_index.resolve_author(item, {7: "Jane Doe"}), "Jane Doe")

    def test_author_from_embed(self):
        item = {"author": 7, "_embedded": {"author": [{"name": "Embed Name"}]}}
        self.assertEqual(wp_index.resolve_author(item, {}), "Embed Name")

    def test_author_fallback(self):
        self.assertEqual(wp_index.resolve_author({"author": 9}, {}), "Author 9")

    def test_parse_public_types(self):
        types_json = {
            "post": {"rest_base": "posts"},
            "page": {"rest_base": "pages"},
            "attachment": {"rest_base": "media"},
            "nav_menu_item": {},
        }
        self.assertEqual(wp_index.parse_public_types(types_json), ["posts", "pages"])


import json as _json


class TestBuildRecord(unittest.TestCase):
    def _load(self):
        path = os.path.join(os.path.dirname(__file__), "fixtures", "sample_post.json")
        with open(path, encoding="utf-8") as f:
            return _json.load(f)

    def test_fields(self):
        record = wp_index.build_record(self._load(), "posts", {7: "Jane Doe"}, None, True)
        self.assertEqual(record["id"], 101)
        self.assertEqual(record["type"], "posts")
        self.assertEqual(record["title"], "A Sample & Real Post")
        self.assertEqual(record["author"], "Jane Doe")
        self.assertEqual(record["slug"], "sample-post")
        self.assertEqual(record["content_markdown"], "Body **text** here.")
        self.assertEqual(record["excerpt"], "Short summary of the post.")
        self.assertEqual(record["word_count"], 3)
        self.assertIn("seo_score", record)
        self.assertFalse(record["stale"])

    def test_no_score(self):
        record = wp_index.build_record(self._load(), "posts", {}, None, False)
        self.assertNotIn("seo_score", record)


if __name__ == "__main__":
    unittest.main()

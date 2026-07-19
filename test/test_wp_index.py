import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import wp_index  # noqa: E402


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(wp_index.slugify("Hello, World! A Test"), "hello-world-a-test")

    def test_empty(self):
        self.assertEqual(wp_index.slugify(""), "")

    def test_truncates(self):
        self.assertEqual(wp_index.slugify("a" * 100, max_length=10), "a" * 10)


class TestSafePathPart(unittest.TestCase):
    def test_plain_value_unchanged(self):
        self.assertEqual(wp_index.safe_path_part("sample-post"), "sample-post")

    def test_preserves_underscores_and_case(self):
        self.assertEqual(wp_index.safe_path_part("jp_pay_order"), "jp_pay_order")

    def test_strips_traversal(self):
        self.assertEqual(wp_index.safe_path_part("../../evil"), "evil")

    def test_strips_slashes_and_regex_chars(self):
        # a real rest_base seen on wordpress.org for wp_font_face
        got = wp_index.safe_path_part(r"font-families/(?P<font_family_id>[\d]+)/font-faces")
        self.assertNotIn("/", got)
        self.assertNotIn("\\", got)
        self.assertNotIn("..", got)

    def test_dots_only_becomes_empty(self):
        self.assertEqual(wp_index.safe_path_part(".."), "")

    def test_none_and_empty(self):
        self.assertEqual(wp_index.safe_path_part(None), "")
        self.assertEqual(wp_index.safe_path_part(""), "")


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

    def test_image_with_alt(self):
        self.assertEqual(
            wp_index.html_to_markdown('<p><img src="https://x.com/i.png" alt="A pic"></p>'),
            "![A pic](https://x.com/i.png)",
        )

    def test_image_without_alt(self):
        self.assertEqual(
            wp_index.html_to_markdown('<img src="https://x.com/i.png">'),
            "![](https://x.com/i.png)",
        )

    def test_image_lazy_data_src(self):
        self.assertEqual(
            wp_index.html_to_markdown('<img data-src="https://x.com/l.png" alt="Lazy">'),
            "![Lazy](https://x.com/l.png)",
        )

    def test_script_contents_suppressed(self):
        self.assertEqual(
            wp_index.html_to_markdown("<p>a</p><script>var x = 1;</script><p>b</p>"),
            "a\n\nb",
        )

    def test_style_contents_suppressed(self):
        self.assertEqual(
            wp_index.html_to_markdown("<style>.x{color:red}</style><p>hi</p>"),
            "hi",
        )

    def test_pre_code_becomes_fenced_block(self):
        self.assertEqual(
            wp_index.html_to_markdown("<pre><code>line1\nline2</code></pre>"),
            "```\nline1\nline2\n```",
        )

    def test_inline_code_stays_inline(self):
        self.assertEqual(
            wp_index.html_to_markdown("<p>use <code>x</code></p>"),
            "use `x`",
        )

    def test_nested_anchors_keep_both_hrefs(self):
        got = wp_index.html_to_markdown(
            '<a href="https://a.com">out <a href="https://b.com">in</a></a>'
        )
        self.assertIn("https://a.com", got)
        self.assertIn("https://b.com", got)

    def test_table_becomes_markdown_table(self):
        html_in = ("<table><tr><th>Feature</th><th>Value</th></tr>"
                   "<tr><td>Speed</td><td>Fast</td></tr></table>")
        self.assertEqual(
            wp_index.html_to_markdown(html_in),
            "| Feature | Value |\n| --- | --- |\n| Speed | Fast |",
        )

    def test_table_cell_pipes_escaped_and_formatting_kept(self):
        html_in = "<table><tr><td>a|b</td><td><strong>x</strong></td></tr></table>"
        got = wp_index.html_to_markdown(html_in)
        self.assertIn("a\\|b", got)
        self.assertIn("**x**", got)

    def test_table_inside_prose(self):
        html_in = "<p>before</p><table><tr><td>cell</td></tr></table><p>after</p>"
        got = wp_index.html_to_markdown(html_in)
        self.assertIn("before", got)
        self.assertIn("| cell |", got)
        self.assertIn("after", got)

    def test_nested_unordered_list_indented(self):
        html_in = "<ul><li>one<ul><li>sub</li></ul></li><li>two</li></ul>"
        self.assertEqual(wp_index.html_to_markdown(html_in), "- one\n  - sub\n- two")

    def test_nested_ordered_list_indented(self):
        html_in = "<ol><li>a<ol><li>b</li></ol></li></ol>"
        self.assertEqual(wp_index.html_to_markdown(html_in), "1. a\n   1. b")


class TestAuthorAndTypes(unittest.TestCase):
    def test_author_from_map(self):
        item = {"author": 7}
        self.assertEqual(wp_index.resolve_author(item, {7: "Jane Doe"}), "Jane Doe")

    def test_author_from_embed(self):
        item = {"author": 7, "_embedded": {"author": [{"name": "Embed Name"}]}}
        self.assertEqual(wp_index.resolve_author(item, {}), "Embed Name")

    def test_author_fallback(self):
        self.assertEqual(wp_index.resolve_author({"author": 9}, {}), "Author 9")

    def test_author_non_dict_embed(self):
        item = {"author": 9, "_embedded": {"author": ["oops"]}}
        self.assertEqual(wp_index.resolve_author(item, {}), "Author 9")

    def test_parse_public_types(self):
        types_json = {
            "post": {"rest_base": "posts"},
            "page": {"rest_base": "pages"},
            "attachment": {"rest_base": "media"},
            "nav_menu_item": {},
        }
        self.assertEqual(wp_index.parse_public_types(types_json), ["posts", "pages"])

    def test_parse_public_types_skips_internal_and_foreign_namespace(self):
        types_json = {
            "post": {"rest_base": "posts"},
            "wp_block": {"rest_base": "blocks"},
            "wp_template": {"rest_base": "templates"},
            "wp_font_face": {"rest_base": "font-families/(?P<font_family_id>[\\d]+)/font-faces"},
            "nav_menu_item": {"rest_base": "menu-items"},
            "jetpack_thing": {"rest_base": "things", "rest_namespace": "jetpack/v1"},
            "product": {"rest_base": "products", "rest_namespace": "wp/v2"},
        }
        self.assertEqual(wp_index.parse_public_types(types_json), ["posts", "products"])


class TestBuildRecord(unittest.TestCase):
    def _load(self):
        path = os.path.join(os.path.dirname(__file__), "fixtures", "sample_post.json")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

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

    def test_terms_media_and_yoast_captured(self):
        item = self._load()
        item["_embedded"] = {
            "wp:term": [[{"taxonomy": "category", "name": "News"}],
                        [{"taxonomy": "post_tag", "name": "AI"}]],
            "wp:featuredmedia": [{"source_url": "https://x.com/f.jpg"}],
        }
        item["yoast_head_json"] = {"description": "d" * 100}
        record = wp_index.build_record(item, "posts", {}, None, True)
        self.assertEqual(record["categories"], ["News"])
        self.assertEqual(record["tags"], ["AI"])
        self.assertEqual(record["featured_image"], "https://x.com/f.jpg")
        self.assertEqual(record["seo_meta_source"], "yoast")

    def test_yoast_description_is_scored(self):
        item = self._load()
        item["yoast_head_json"] = {"description": "d" * 100}
        with_yoast = wp_index.build_record(item, "posts", {}, None, True)
        without = wp_index.build_record(self._load(), "posts", {}, None, True)
        self.assertEqual(without["seo_meta_source"], "excerpt")
        # fixture excerpt is 26 chars (+20); the yoast description is 100 (+40)
        self.assertEqual(with_yoast["seo_score"] - without["seo_score"], 20)


class TestMetadataExtraction(unittest.TestCase):
    def test_extract_terms(self):
        item = {"_embedded": {"wp:term": [
            [{"taxonomy": "category", "name": "News"},
             {"taxonomy": "category", "name": "Tech"}],
            [{"taxonomy": "post_tag", "name": "AI"}],
            "not-a-list",
        ]}}
        categories, tags = wp_index.extract_terms(item)
        self.assertEqual(categories, ["News", "Tech"])
        self.assertEqual(tags, ["AI"])

    def test_extract_terms_absent(self):
        self.assertEqual(wp_index.extract_terms({}), ([], []))

    def test_extract_featured_image(self):
        item = {"_embedded": {"wp:featuredmedia": [{"source_url": "https://x.com/f.jpg"}]}}
        self.assertEqual(wp_index.extract_featured_image(item), "https://x.com/f.jpg")

    def test_extract_featured_image_forbidden_shape(self):
        # protected media embeds as an error object with no source_url
        item = {"_embedded": {"wp:featuredmedia": [{"code": "rest_forbidden"}]}}
        self.assertEqual(wp_index.extract_featured_image(item), "")


def _sample_record():
    return {
        "id": 101, "type": "posts", "title": "Sample Title", "slug": "sample",
        "status": "publish", "url": "https://example.com/sample/",
        "date": "2024-03-15T09:30:00", "modified": "2024-03-20T11:00:00",
        "author": "Jane Doe", "excerpt": "A summary.", "word_count": 3,
        "content_markdown": "Body text.", "stale": False,
        "seo_score": 80, "seo_grade": "B",
    }


class TestRenderers(unittest.TestCase):
    def test_markdown_has_frontmatter_and_body(self):
        md = wp_index.markdown_for_record(_sample_record())
        self.assertTrue(md.startswith("---\n"))
        self.assertIn('title: "Sample Title"', md)
        self.assertIn("seo_grade: B", md)
        self.assertIn("# Sample Title", md)
        self.assertIn("Body text.", md)

    def test_knowledge_base(self):
        kb = wp_index.knowledge_base_markdown([_sample_record()])
        self.assertIn("# Content Knowledge Base", kb)
        self.assertIn("Total items: 1", kb)
        self.assertIn("## Sample Title", kb)

    def test_markdown_escapes_url(self):
        rec = _sample_record()
        rec["url"] = "https://x.com/?a=1: 2"
        md = wp_index.markdown_for_record(rec)
        self.assertIn('url: "https://x.com/?a=1: 2"', md)

    def test_frontmatter_includes_terms_and_image(self):
        rec = _sample_record()
        rec["categories"] = ["News", "Tech"]
        rec["tags"] = ["AI"]
        rec["featured_image"] = "https://x.com/f.jpg"
        rec["seo_meta_source"] = "excerpt"
        md = wp_index.markdown_for_record(rec)
        self.assertIn('categories: ["News", "Tech"]', md)
        self.assertIn('tags: ["AI"]', md)
        self.assertIn('featured_image: "https://x.com/f.jpg"', md)
        self.assertIn("seo_meta_source: excerpt", md)

    def test_knowledge_base_lists_terms(self):
        rec = _sample_record()
        rec["categories"] = ["News"]
        rec["tags"] = ["AI", "Dental"]
        kb = wp_index.knowledge_base_markdown([rec])
        self.assertIn("- Categories: News", kb)
        self.assertIn("- Tags: AI, Dental", kb)


class TestWriters(unittest.TestCase):
    def test_csv_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = wp_index.write_csv(d, "posts", [_sample_record()])
            with open(path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "Sample Title")

    def test_json_archive_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = wp_index.write_json_archive(d, {"site": "x", "n": 1})
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["n"], 1)

    def test_markdown_files_written(self):
        with tempfile.TemporaryDirectory() as d:
            paths = wp_index.write_markdown_files(d, "posts", [_sample_record()])
            self.assertEqual(len(paths), 1)
            self.assertTrue(os.path.exists(paths[0]))
            self.assertTrue(paths[0].endswith("2024-03-15_sample.md"))

    def test_markdown_filename_collision(self):
        with tempfile.TemporaryDirectory() as d:
            r1 = _sample_record()
            r2 = dict(_sample_record())
            r2["id"] = 102
            paths = wp_index.write_markdown_files(d, "posts", [r1, r2])
            self.assertEqual(len(paths), 2)
            self.assertEqual(len(set(paths)), 2)
            self.assertTrue(all(os.path.exists(p) for p in paths))

    def test_traversal_slug_stays_inside_out_dir(self):
        with tempfile.TemporaryDirectory() as d:
            rec = _sample_record()
            rec["slug"] = "../../evil"
            rec["date"] = ""
            paths = wp_index.write_markdown_files(d, "posts", [rec])
            self.assertEqual(os.path.basename(paths[0]), "evil.md")
            real = os.path.realpath(paths[0])
            self.assertTrue(real.startswith(os.path.realpath(d) + os.sep))

    def test_malformed_date_dropped_from_filename(self):
        with tempfile.TemporaryDirectory() as d:
            rec = _sample_record()
            rec["date"] = "banana2024-03"
            paths = wp_index.write_markdown_files(d, "posts", [rec])
            self.assertEqual(os.path.basename(paths[0]), "sample.md")

    def test_flatten_joins_list_fields(self):
        row = wp_index.flatten_for_table({"categories": ["A", "B"], "tags": [], "id": 1})
        self.assertEqual(row["categories"], "A; B")
        self.assertEqual(row["tags"], "")
        self.assertEqual(row["id"], 1)

    def test_csv_includes_joined_categories(self):
        rec = _sample_record()
        rec["categories"] = ["News", "Tech"]
        with tempfile.TemporaryDirectory() as d:
            path = wp_index.write_csv(d, "posts", [rec])
            with open(path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["categories"], "News; Tech")


class TestCheckpoints(unittest.TestCase):
    def test_roundtrip_with_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            cp = os.path.join(d, ".checkpoints")
            self.assertIsNone(wp_index.load_checkpoint(cp, "items_posts"))
            wp_index.save_checkpoint(cp, "items_posts", [{"id": 1}])
            got = wp_index.load_checkpoint(cp, "items_posts")
            self.assertEqual(got["items"], [{"id": 1}])
            self.assertTrue(got["fetched_at"])

    def test_legacy_bare_list_still_loads(self):
        with tempfile.TemporaryDirectory() as d:
            cp = os.path.join(d, ".checkpoints")
            os.makedirs(cp)
            with open(os.path.join(cp, "items_posts.json"), "w", encoding="utf-8") as f:
                json.dump([{"id": 7}], f)
            got = wp_index.load_checkpoint(cp, "items_posts")
            self.assertEqual(got["items"], [{"id": 7}])
            self.assertIsNone(got["fetched_at"])

    def test_clear_removes_files_and_dir(self):
        with tempfile.TemporaryDirectory() as d:
            cp = os.path.join(d, ".checkpoints")
            wp_index.save_checkpoint(cp, "items_posts", [1])
            wp_index.clear_checkpoints(cp)
            self.assertIsNone(wp_index.load_checkpoint(cp, "items_posts"))
            self.assertFalse(os.path.isdir(cp))


class TestHttp(unittest.TestCase):
    def test_build_headers_public(self):
        headers = wp_index.build_headers(None, None)
        self.assertIn("User-Agent", headers)
        self.assertNotIn("Authorization", headers)

    def test_build_headers_auth(self):
        headers = wp_index.build_headers("user", "app pass")
        self.assertTrue(headers["Authorization"].startswith("Basic "))

    def _ok_response(self, body=b'{"ok": true}', header_items=()):
        fake = mock.MagicMock()
        fake.read.return_value = body
        fake.headers.items.return_value = list(header_items)
        cm = mock.MagicMock()
        cm.__enter__.return_value = fake
        return cm

    def test_fetch_json_parses_body_and_headers(self):
        cm = self._ok_response(b'{"hello": "world"}', [("X-WP-TotalPages", "3")])
        with mock.patch("wp_index.urllib.request.urlopen", return_value=cm):
            data, headers = wp_index.fetch_json("https://x/wp-json/wp/v2/posts", {})
        self.assertEqual(data, {"hello": "world"})
        self.assertEqual(headers.get("x-wp-totalpages"), "3")

    def test_fetch_json_retries_on_503(self):
        err = wp_index.urllib.error.HTTPError("u", 503, "busy", {}, None)
        with mock.patch("wp_index.urllib.request.urlopen",
                        side_effect=[err, self._ok_response()]), \
             mock.patch("wp_index.time.sleep"):
            data, _ = wp_index.fetch_json("https://x", {}, delay=0)
        self.assertEqual(data, {"ok": True})

    def test_fetch_json_retries_on_timeout(self):
        # A read timeout raises TimeoutError (an OSError, not a URLError); it must be
        # caught and retried, not crash the run. Regression for the live-run failure.
        with mock.patch("wp_index.urllib.request.urlopen",
                        side_effect=[TimeoutError("read timed out"), self._ok_response()]), \
             mock.patch("wp_index.time.sleep"):
            data, _ = wp_index.fetch_json("https://x", {}, delay=0)
        self.assertEqual(data, {"ok": True})

    def test_fetch_json_retry_after_http_date_does_not_crash(self):
        # Retry-After is allowed to be an HTTP date; float() on it must not blow up
        err = wp_index.urllib.error.HTTPError(
            "u", 503, "busy", {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None
        )
        with mock.patch("wp_index.urllib.request.urlopen",
                        side_effect=[err, self._ok_response()]), \
             mock.patch("wp_index.time.sleep"):
            data, _ = wp_index.fetch_json("https://x", {}, delay=0)
        self.assertEqual(data, {"ok": True})

    def test_fetch_json_non_json_body_raises_clear_error(self):
        cm = self._ok_response(b"<html>challenge page</html>")
        with mock.patch("wp_index.urllib.request.urlopen", return_value=cm):
            with self.assertRaises(ValueError) as ctx:
                wp_index.fetch_json("https://x/wp-json/wp/v2/posts", {})
        self.assertIn("non-JSON", str(ctx.exception))

    def test_fetch_all_paginates(self):
        pages = {
            1: ([{"id": 1}, {"id": 2}], {"x-wp-totalpages": "2"}),
            2: ([{"id": 3}], {"x-wp-totalpages": "2"}),
        }
        seq = {"n": 0}

        def fake_fetch(url, headers, **kw):
            seq["n"] += 1
            return pages[seq["n"]]

        with mock.patch("wp_index.fetch_json", side_effect=fake_fetch), \
             mock.patch("wp_index.time.sleep"):
            items = wp_index.fetch_all("https://x/wp-json/wp/v2", "posts", {}, per_page=50, delay=0)
        self.assertEqual([i["id"] for i in items], [1, 2, 3])

    def test_fetch_all_continues_without_totalpages_header(self):
        # a proxy stripping X-WP-TotalPages must not truncate the crawl to page 1
        pages = {
            1: ([{"id": 1}, {"id": 2}], {}),
            2: ([{"id": 3}], {}),
            3: ([], {}),
        }
        seq = {"n": 0}

        def fake_fetch(url, headers, **kw):
            seq["n"] += 1
            return pages[seq["n"]]

        with mock.patch("wp_index.fetch_json", side_effect=fake_fetch), \
             mock.patch("wp_index.time.sleep"):
            items = wp_index.fetch_all("https://x/wp-json/wp/v2", "posts", {}, per_page=50, delay=0)
        self.assertEqual([i["id"] for i in items], [1, 2, 3])

    def test_fetch_all_dedupes_shifted_pages(self):
        # a post published mid-crawl shifts pagination; id 2 appears on both pages
        pages = {
            1: ([{"id": 1}, {"id": 2}], {"x-wp-totalpages": "2"}),
            2: ([{"id": 2}, {"id": 3}], {"x-wp-totalpages": "2"}),
        }
        seq = {"n": 0}

        def fake_fetch(url, headers, **kw):
            seq["n"] += 1
            return pages[seq["n"]]

        with mock.patch("wp_index.fetch_json", side_effect=fake_fetch), \
             mock.patch("wp_index.time.sleep"):
            items = wp_index.fetch_all("https://x/wp-json/wp/v2", "posts", {}, per_page=2, delay=0)
        self.assertEqual([i["id"] for i in items], [1, 2, 3])

    def test_verify_auth_accepts_valid_user(self):
        with mock.patch("wp_index.fetch_json", return_value=({"id": 5, "name": "j"}, {})):
            self.assertTrue(wp_index.verify_auth("https://x/wp-json/wp/v2", {}))

    def test_verify_auth_rejects_401(self):
        err = wp_index.urllib.error.HTTPError("u", 401, "nope", {}, None)
        with mock.patch("wp_index.fetch_json", side_effect=err):
            self.assertFalse(wp_index.verify_auth("https://x/wp-json/wp/v2", {}))


class TestKnowledgeBaseWriter(unittest.TestCase):
    def _records(self, n):
        records = []
        for i in range(n):
            rec = _sample_record()
            rec["id"] = 100 + i
            rec["title"] = "Post %d" % i
            records.append(rec)
        return records

    def test_single_file_under_limit(self):
        with tempfile.TemporaryDirectory() as d:
            paths = wp_index.write_knowledge_base(d, self._records(3))
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0].endswith("knowledge-base.md"))
            self.assertTrue(os.path.isfile(paths[0]))

    def test_splits_when_over_limit(self):
        with tempfile.TemporaryDirectory() as d:
            paths = wp_index.write_knowledge_base(d, self._records(6), max_bytes=300)
            self.assertGreater(len(paths), 1)
            self.assertFalse(os.path.isfile(os.path.join(d, "index", "knowledge-base.md")))
            for p in paths:
                self.assertTrue(os.path.isfile(p))
            first = open(paths[0], encoding="utf-8").read()
            self.assertIn("part 1 of %d" % len(paths), first)

    def test_rerun_cleans_stale_shape(self):
        # a split run followed by a single-file run must not leave old parts behind
        with tempfile.TemporaryDirectory() as d:
            split = wp_index.write_knowledge_base(d, self._records(6), max_bytes=300)
            self.assertGreater(len(split), 1)
            single = wp_index.write_knowledge_base(d, self._records(2))
            self.assertEqual(len(single), 1)
            leftovers = [n for n in os.listdir(os.path.join(d, "index"))
                         if n.startswith("knowledge-base-")]
            self.assertEqual(leftovers, [])


class TestMainValidation(unittest.TestCase):
    def test_bad_since_exits_before_any_network(self):
        with mock.patch("wp_index.detect_rest_api") as detect, \
             contextlib.redirect_stdout(io.StringIO()) as out:
            rc = wp_index.main(["--site", "https://example.com", "--since", "not-a-date"])
        self.assertEqual(rc, 2)
        self.assertIn("--since", out.getvalue())
        detect.assert_not_called()


if __name__ == "__main__":
    unittest.main()

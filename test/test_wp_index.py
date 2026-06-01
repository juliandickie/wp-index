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


if __name__ == "__main__":
    unittest.main()

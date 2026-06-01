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


if __name__ == "__main__":
    unittest.main()

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))

import build  # noqa: E402


class RenderTests(unittest.TestCase):
    def test_escapes_plain_keys_and_keeps_html_keys(self):
        errors = []
        out = build.render("{{a}}|{{b_html}}", {}, {"a": "<b>&", "b_html": "<b>"}, errors, "t")
        self.assertEqual(out, "&lt;b&gt;&amp;|<b>")
        self.assertEqual(errors, [])

    def test_missing_key_is_reported(self):
        errors = []
        build.render("{{yok}}", {}, {}, errors, "sayfa")
        self.assertEqual(len(errors), 1)
        self.assertIn("yok", errors[0])

    def test_context_overrides_strings(self):
        errors = []
        self.assertEqual(build.render("{{x}}", {"x": "ctx"}, {"x": "str"}, errors, "t"), "ctx")

    def test_urls(self):
        self.assertEqual(build.page_url("tr", "index"), "/")
        self.assertEqual(build.page_url("en", "index"), "/en/")
        self.assertEqual(build.page_url("en", "kvkk"), "/en/kvkk/")


class BuildTests(unittest.TestCase):
    def build_to(self, theme, **kw):
        tmp = tempfile.mkdtemp()
        out = Path(tmp) / "out"
        build.build(theme, out, "https://alig.tech", kw.get("noindex", False))
        return out

    def test_both_themes_build_all_pages(self):
        for theme in build.THEMES:
            out = self.build_to(theme)
            for rel in ("index.html", "en/index.html", "kvkk/index.html", "en/cerez/index.html",
                        "assets/style.css", "assets/base.css", "assets/failover.js", "sitemap.xml", "robots.txt"):
                self.assertTrue((out / rel).is_file(), f"{theme}: {rel}")
            self.assertNotIn("{{", (out / "index.html").read_text(encoding="utf-8"))

    def test_unused_fonts_are_pruned(self):
        a = self.build_to("a")
        names = {p.name for p in (a / "assets" / "fonts").iterdir()}
        self.assertIn("schibsted-grotesk-latin.woff2", names)
        self.assertFalse(any(n.startswith("source-serif") for n in names))

    def test_build_is_reproducible(self):
        one = (self.build_to("a") / "MANIFEST.sha256").read_text()
        two = (self.build_to("a") / "MANIFEST.sha256").read_text()
        self.assertEqual(one, two)

    def test_manifest_matches_files(self):
        out = self.build_to("b")
        for line in (out / "MANIFEST.sha256").read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), digest)

    def test_noindex_build(self):
        out = self.build_to("a", noindex=True)
        self.assertIn("noindex", (out / "index.html").read_text(encoding="utf-8"))
        self.assertIn("Disallow: /", (out / "robots.txt").read_text())
        self.assertFalse((out / "sitemap.xml").exists())

    def test_turkish_text_survives(self):
        out = self.build_to("a")
        text = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn("düştüğünde", text)
        self.assertIn('hreflang="en" href="https://alig.tech/en/"', text)


if __name__ == "__main__":
    unittest.main()

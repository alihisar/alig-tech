import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ci"))

import check_banned  # noqa: E402
import check_external  # noqa: E402
import check_html  # noqa: E402
import check_i18n  # noqa: E402
import check_links  # noqa: E402
import check_placeholders  # noqa: E402
import check_secrets  # noqa: E402
import check_size  # noqa: E402
import check_workflows  # noqa: E402

GOOD = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>t</title>
<link rel="alternate" hreflang="tr" href="https://alig.tech/"><link rel="alternate" hreflang="en" href="https://alig.tech/en/">
<link rel="alternate" hreflang="x-default" href="https://alig.tech/"></head>
<body><h1 id="top">b</h1><a href="#top">x</a></body></html>"""


def tree(files):
    base = Path(tempfile.mkdtemp())
    for name, text in files.items():
        p = base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return base


class ExternalTests(unittest.TestCase):
    def test_flags_foreign_script_and_css(self):
        d = tree({
            "index.html": GOOD.replace("</head>", '<script src="https://cdn.example.com/x.js"></script></head>'),
            "a.css": "@font-face{src:url(https://fonts.example.com/f.woff2)}",
        })
        problems = check_external.check(d)
        self.assertEqual(len(problems), 2, problems)

    def test_allows_own_host_and_local(self):
        d = tree({
            "index.html": GOOD.replace("</head>", '<script src="https://alig.tech/x.js"></script>'
                                                    '<link rel="stylesheet" href="/s.css"></head>'),
            "s.css": "a{background:url(/f.png)}",
        })
        self.assertEqual(check_external.check(d), [])


class HtmlTests(unittest.TestCase):
    def test_good_page(self):
        self.assertEqual(check_html.check(tree({"index.html": GOOD})), [])

    def test_inline_script_and_style_flagged(self):
        page = GOOD.replace("<h1", '<script>1</script><p style="x:y" onclick="a()">p</p><h1')
        problems = check_html.check(tree({"index.html": page}))
        self.assertTrue(any("betik" in p for p in problems))
        self.assertTrue(any("style" in p for p in problems))
        self.assertTrue(any("olay" in p for p in problems))

    def test_ldjson_allowed_and_svg_title_ignored(self):
        page = GOOD.replace("</head>", '<script type="application/ld+json">{}</script></head>').replace(
            "<h1", '<svg><title>x</title><path d="M0 0"/></svg><h1')
        self.assertEqual(check_html.check(tree({"index.html": page})), [])

    def test_unlabelled_input_flagged(self):
        page = GOOD.replace("<h1", '<input id="q" type="text"><h1')
        self.assertTrue(any("etiketsiz" in p for p in check_html.check(tree({"index.html": page}))))

    def test_duplicate_id_and_unbalanced(self):
        page = GOOD.replace("<h1", '<div id="top"><h1')
        problems = check_html.check(tree({"index.html": page}))
        self.assertTrue(any("yinelenen" in p for p in problems))


class LinksTests(unittest.TestCase):
    def test_broken_and_missing_fragment(self):
        d = tree({
            "index.html": GOOD.replace("</body>", '<a href="/yok/">y</a><a href="/b/#nope">n</a><a href="/b/#ok">k</a></body>'),
            "b/index.html": GOOD.replace('id="top"', 'id="ok"').replace('href="#top"', 'href="#ok"'),
        })
        problems = check_links.check(d)
        self.assertEqual(len(problems), 2, problems)

    def test_form_action_ignored(self):
        d = tree({"index.html": GOOD.replace("</body>", '<form action="/api/x"></form></body>')})
        self.assertEqual(check_links.check(d), [])


class SecretsTests(unittest.TestCase):
    def test_detects_key_and_ignores_examples(self):
        base = tree({
            "a.txt": "aws=AKIA" + "ABCDEFGHIJKLMNOP\n",
            "b.env": "PASSWORD=CHANGE_ME_please_replace\n",
            "c.txt": "api_key = 'abcdefghijklmnop1234'\n",
        })
        problems = check_secrets.scan_tree(base, set())
        self.assertEqual(sorted(p.split(":")[0] for p in problems), ["a.txt", "c.txt"])


class WorkflowTests(unittest.TestCase):
    def test_unpinned_action_flagged(self):
        sha = "a" * 40
        root = tree({".github/workflows/x.yml": (
            f"steps:\n  - uses: actions/checkout@v4\n  - uses: actions/setup@{sha} # v1\n  - uses: ./local\n")})
        problems = check_workflows.check(root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("actions/checkout@v4", problems[0])

    def test_repo_workflow_is_pinned(self):
        self.assertEqual(check_workflows.check(), [])


class PlaceholderTests(unittest.TestCase):
    def test_release_fails_only_with_flag(self):
        d = tree({"index.html": GOOD.replace("<h1", "<p>[doldurulacak: ad]</p><h1")})
        self.assertEqual(check_placeholders.check(d, release=False), [])
        self.assertEqual(len(check_placeholders.check(d, release=True)), 1)


class SizeTests(unittest.TestCase):
    def test_budget(self):
        d = tree({
            "index.html": GOOD.replace("</head>", '<link rel="stylesheet" href="/s.css"></head>'),
            "en/index.html": GOOD,
            "s.css": "a{b:c}" + "x" * 5000,
        })
        self.assertEqual(check_size.check(d, 100000), [])
        self.assertEqual(len(check_size.check(d, 3000)), 1)


class BannedAndI18nTests(unittest.TestCase):
    def root(self, tr, en):
        return tree({"site/i18n/tr.json": json.dumps(tr), "site/i18n/en.json": json.dumps(en)})

    def test_banned_phrase_and_css(self):
        root = self.root({"a": "Sizi güçlendiririz"}, {"a": "We empower you"})
        dist = tree({"index.html": GOOD, "s.css": "a{background:linear-gradient(red,blue)}"})
        problems = check_banned.check(dist, root)
        self.assertEqual(len(problems), 3, problems)

    def test_i18n_parity_and_pairs(self):
        root = self.root({"a": "x", "b": "y"}, {"a": "x"})
        dist = tree({"index.html": GOOD, "kvkk/index.html": GOOD})
        problems = check_i18n.check(dist, root)
        self.assertTrue(any("en.json'da yok: b" in p for p in problems))
        self.assertTrue(any("karsilik dil sayfasi yok" in p for p in problems))


if __name__ == "__main__":
    unittest.main()

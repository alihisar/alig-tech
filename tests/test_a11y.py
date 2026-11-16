"""ALIG-UX-001: tests of the accessibility check (ci/check_a11y.py). Bad HTML/CSS must fail; the built site must pass."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ci"))
sys.path.insert(0, str(ROOT / "build"))

import check_a11y  # noqa: E402

PAGE = """<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>t</title></head>
<body>{body}</body></html>"""

GOOD_BODY = '<h1>a</h1><h2>b</h2><h3>c</h3><h2>d</h2><img src="/x.png" alt="x"><img src="/y.png" alt="">' \
            '<label for="q">q</label><input id="q" type="text"><input type="hidden" name="h">'

TOKENS = {
    "bg": "#ffffff", "fg": "#16233b", "muted": "#4d5b73", "input-bg": "#ffffff", "line-strong": "#767676",
    "signal": "#2a3fd6", "on-signal": "#ffffff", "focus": "#2a3fd6",
    "term-bg": "#0f1a33", "term-fg": "#dbe3f2", "term-muted": "#9aa9c4", "ok": "#5fd0b0", "bad": "#f08a7c",
}
FOCUS_CSS = ":focus-visible{outline:2px solid var(--focus);outline-offset:3px}.console{--focus:var(--term-fg)}"


def css_of(tokens=None, extra=FOCUS_CSS):
    t = dict(TOKENS, **(tokens or {}))
    return ":root{" + ";".join(f"--{k}:{v}" for k, v in t.items()) + "}" + extra


def site(pages=None, css=None):
    """A minimal built-site tree: pages {path: html}, assets/style.css."""
    base = Path(tempfile.mkdtemp())
    pages = pages if pages is not None else {
        "index.html": PAGE.format(lang="tr", body=GOOD_BODY), "en/index.html": PAGE.format(lang="en", body=GOOD_BODY)}
    for name, text in pages.items():
        p = base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (base / "assets").mkdir(exist_ok=True)
    (base / "assets" / "style.css").write_text(css if css is not None else css_of(), encoding="utf-8")
    return base


def one(body, lang="tr", path="index.html"):
    """A site whose only page (plus a valid page of the other language) carries the given body."""
    other = {"en/index.html": PAGE.format(lang="en", body=GOOD_BODY)} if path == "index.html" else \
            {"index.html": PAGE.format(lang="tr", body=GOOD_BODY)}
    return site({path: PAGE.format(lang=lang, body=body), **other})


class ContrastMathTests(unittest.TestCase):
    def test_known_ratios(self):
        self.assertAlmostEqual(check_a11y.contrast("#000000", "#ffffff"), 21.0, places=2)
        self.assertAlmostEqual(check_a11y.contrast("#ffffff", "#ffffff"), 1.0, places=2)
        # reference value: #767676 on white is the well-known 4.54:1
        self.assertAlmostEqual(check_a11y.contrast("#767676", "#ffffff"), 4.54, places=2)

    def test_short_hex_and_rgb(self):
        self.assertAlmostEqual(check_a11y.contrast("#fff", "rgb(0,0,0)"), 21.0, places=2)

    def test_alpha_is_composited_over_background(self):
        # 50 percent black over white is mid grey (about 3.95:1), not black
        self.assertAlmostEqual(check_a11y.contrast("rgba(0,0,0,.5)", "#ffffff"), 3.95, places=1)


class HtmlTests(unittest.TestCase):
    def test_good_site_passes(self):
        self.assertEqual(check_a11y.check(site()), [])

    def test_img_without_alt_fails(self):
        self.assertTrue(any("alt" in p for p in check_a11y.check(one('<h1>a</h1><img src="/x.png">'))))

    def test_img_with_empty_alt_passes(self):
        self.assertEqual(check_a11y.check(one('<h1>a</h1><img src="/x.png" alt="">')), [])

    def test_unlabelled_field_fails(self):
        for tag in ('<input id="q" type="text">', '<select id="q"></select>', '<textarea id="q"></textarea>',
                    '<input type="email">'):
            with self.subTest(tag=tag):
                self.assertTrue(any("label" in p for p in check_a11y.check(one("<h1>a</h1>" + tag))), tag)

    def test_label_for_wrapping_and_aria_pass(self):
        for body in ('<label for="q">x</label><input id="q">', '<label>x <input name="q"></label>',
                     '<input aria-label="x">', '<span id="l">x</span><input aria-labelledby="l">'):
            with self.subTest(body=body):
                self.assertEqual(check_a11y.check(one("<h1>a</h1>" + body)), [])

    def test_label_for_pointing_nowhere_fails(self):
        body = '<h1>a</h1><label for="zzz">x</label><input id="q">'
        self.assertTrue(any("label" in p for p in check_a11y.check(one(body))))

    def test_hidden_and_submit_need_no_label(self):
        self.assertEqual(check_a11y.check(one('<h1>a</h1><input type="hidden" name="a"><input type="submit" value="x">')), [])

    def test_heading_order_skip_fails(self):
        problems = check_a11y.check(one("<h1>a</h1><h3>c</h3>"))
        self.assertTrue(any("heading" in p for p in problems), problems)

    def test_heading_going_back_up_passes(self):
        self.assertEqual(check_a11y.check(one("<h1>a</h1><h2>b</h2><h3>c</h3><h2>d</h2>")), [])

    def test_first_heading_must_be_h1_and_one_h1(self):
        self.assertTrue(any("heading" in p for p in check_a11y.check(one("<h2>b</h2><h1>a</h1>"))))
        self.assertTrue(any("h1" in p for p in check_a11y.check(one("<h1>a</h1><h1>b</h1>"))))
        self.assertTrue(any("h1" in p for p in check_a11y.check(one("<p>no heading</p>"))))

    def test_svg_headings_ignored(self):
        self.assertEqual(check_a11y.check(one("<h1>a</h1><svg><title>x</title></svg>")), [])

    def test_missing_lang_fails(self):
        base = site({"index.html": "<!doctype html><html><head><title>t</title></head><body><h1>a</h1></body></html>",
                     "en/index.html": PAGE.format(lang="en", body=GOOD_BODY)})
        self.assertTrue(any("lang" in p for p in check_a11y.check(base)))

    def test_lang_must_match_language_directory(self):
        self.assertTrue(any("lang" in p for p in check_a11y.check(one("<h1>a</h1>", lang="en", path="index.html"))))
        self.assertTrue(any("lang" in p for p in check_a11y.check(one("<h1>a</h1>", lang="tr", path="en/index.html"))))
        self.assertTrue(any("lang" in p for p in check_a11y.check(one("<h1>a</h1>", lang="", path="index.html"))))

    def test_both_languages_required(self):
        base = site({"index.html": PAGE.format(lang="tr", body=GOOD_BODY)})
        self.assertTrue(any("en/" in p for p in check_a11y.check(base)))

    def test_no_pages_fails(self):
        self.assertTrue(check_a11y.check(site({})))


class FocusTests(unittest.TestCase):
    def test_missing_focus_visible_fails(self):
        self.assertTrue(any("focus-visible" in p for p in check_a11y.check(site(css=css_of(extra="a{color:red}")))))

    def test_focus_visible_without_outline_fails(self):
        css = css_of(extra=":focus-visible{color:red}")
        self.assertTrue(any("focus-visible" in p for p in check_a11y.check(site(css=css))))

    def test_outline_removed_fails(self):
        for rule in ("a{outline:none}", "button:focus{outline:0}", ":focus-visible{outline:none}"):
            with self.subTest(rule=rule):
                css = css_of(extra=FOCUS_CSS + rule)
                self.assertTrue(any("outline" in p for p in check_a11y.check(site(css=css))), rule)

    def test_console_focus_ring_needs_its_own_colour(self):
        # focus ring colour equal to the console background is invisible there unless .console overrides --focus
        css = css_of({"focus": "#0f1a33"}, extra=":focus-visible{outline:2px solid var(--focus)}")
        self.assertTrue(any("console" in p for p in check_a11y.check(site(css=css))))

    def test_focus_colour_needs_3_to_1(self):
        css = css_of({"focus": "#fafafa"})
        self.assertTrue(any("focus" in p and "3" in p for p in check_a11y.check(site(css=css))))


class ContrastTests(unittest.TestCase):
    def test_low_contrast_text_fails(self):
        problems = check_a11y.check(site(css=css_of({"muted": "#aaaaaa"})))
        self.assertTrue(any("muted" in p and "4.5" in p for p in problems), problems)

    def test_button_pair_fails(self):
        problems = check_a11y.check(site(css=css_of({"signal": "#f2b441", "on-signal": "#ffffff"})))
        self.assertTrue(any("on-signal" in p for p in problems), problems)

    def test_console_pairs_fail(self):
        problems = check_a11y.check(site(css=css_of({"term-muted": "#445566"})))
        self.assertTrue(any("term-muted" in p for p in problems), problems)

    def test_threshold_is_not_loosened(self):
        # #777777 on white is 4.48:1, just under 4.5:1: must fail for text
        problems = check_a11y.check(site(css=css_of({"muted": "#777777"})))
        self.assertTrue(any("muted" in p for p in problems), problems)

    def test_non_text_boundary_needs_3_to_1(self):
        problems = check_a11y.check(site(css=css_of({"line-strong": "#cccccc"})))
        self.assertTrue(any("line-strong" in p for p in problems), problems)

    def test_missing_required_token_fails(self):
        css = ":root{--bg:#fff}" + FOCUS_CSS
        self.assertTrue(any("--fg" in p for p in check_a11y.check(site(css=css))))

    def test_var_reference_resolved(self):
        css = css_of({"muted": "var(--fg)"})
        self.assertEqual(check_a11y.check(site(css=css)), [])

    def test_later_stylesheet_overrides_token(self):
        base = site(css=css_of())
        (base / "assets" / "zz.css").write_text(":root{--muted:#cccccc}", encoding="utf-8")
        self.assertTrue(any("muted" in p for p in check_a11y.check(base)))

    def test_theme_specific_pairs(self):
        # theme c: signal-coloured links sit on the page background
        problems = check_a11y.check(site(css=css_of({"signal": "#9fb0ff", "on-signal": "#000000"})), theme="c")
        self.assertTrue(any("signal" in p for p in problems), problems)


class BuiltSiteTests(unittest.TestCase):
    """The real site, all three themes (the CI step builds the same trees)."""

    def test_all_themes_pass(self):
        import build as site_build
        for theme in site_build.THEMES:
            with self.subTest(theme=theme):
                out = Path(tempfile.mkdtemp()) / theme
                self.assertEqual(site_build.main(["--theme", theme, "--out", str(out)]), 0)
                self.assertEqual(check_a11y.check(out, theme=theme), [])


class WiringTests(unittest.TestCase):
    def test_run_all_has_an_accessibility_step_over_all_themes(self):
        src = (ROOT / "ci" / "run_all.py").read_text(encoding="utf-8")
        self.assertIn("import check_a11y", src)
        self.assertIn('step("accessibility"', src)
        self.assertIn("for theme in site_build.THEMES", src[src.index("def a11y"):src.index('step("accessibility"')])

    def test_command_line_exit_codes(self):
        self.assertEqual(check_a11y.main([str(site())]), 0)
        self.assertEqual(check_a11y.main([str(one("<h1>a</h1><img src='/x.png'>"))]), 1)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""alig.tech statik site derleyicisi.

Yalnizca Python standart kutuphanesi. Ayni girdi ayni ciktiyi uretir:
zaman damgasi yok, dosyalar sirali yazilir, manifest icerik ozetlerinden olusur.

Kullanim:
  python3 build/build.py --theme a              # dist/a
  python3 build/build.py --theme all            # dist/a ve dist/b
  python3 build/build.py --theme a --out /tmp/x --noindex
"""
import argparse
import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
LANGS = ("tr", "en")
THEMES = ("a", "b", "c")
SHARED_PAGES = ("kvkk", "cerez", "tesekkurler", "demo", "saglik-taramasi", "tarama-hazirlik")
TOKEN = re.compile(r"\{\{\s*([A-Za-z0-9_:.\-]+)\s*\}\}")
MAX_INCLUDE_DEPTH = 5


class BuildError(Exception):
    pass


def read(path):
    return Path(path).read_text(encoding="utf-8")


def render(text, ctx, strings, errors, where, depth=0):
    """{{anahtar}} -> kacislanmis metin, {{anahtar_html}} -> ham, {{include:ad}} -> partial."""
    if depth > MAX_INCLUDE_DEPTH:
        raise BuildError(f"{where}: include derinligi asildi")

    def sub(match):
        key = match.group(1)
        if key.startswith("include:"):
            name = key.split(":", 1)[1]
            path = SITE / "partials" / f"{name}.html"
            if not path.is_file():
                errors.append(f"{where}: partial yok: {name}")
                return ""
            return render(read(path), ctx, strings, errors, f"{where}>{name}", depth + 1)
        if key in ctx:
            value = ctx[key]
        elif key in strings:
            value = strings[key]
        else:
            errors.append(f"{where}: anahtar yok: {key}")
            return ""
        return value if key.endswith("_html") else html.escape(value, quote=True)

    return TOKEN.sub(sub, text)


def page_url(lang, slug):
    base = "/" if lang == "tr" else "/en/"
    return base if slug == "index" else f"{base}{slug}/"


def out_file(out, lang, slug):
    rel = page_url(lang, slug).strip("/")
    return (out / rel / "index.html") if rel else (out / "index.html")


def jsonld(base_url, strings):
    graph = [
        {
            "@type": "Organization",
            "@id": f"{base_url}/#org",
            "name": "alig.tech",
            "url": f"{base_url}/",
            "description": strings["meta_description"],
        }
    ]
    for i in range(1, 6):
        graph.append(
            {
                "@type": "Service",
                "name": strings[f"svc{i}_name"],
                "description": strings[f"svc{i}_text"],
                "provider": {"@id": f"{base_url}/#org"},
            }
        )
    data = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, indent=1)
    data = data.replace("</", "<\\/")
    return f'<script type="application/ld+json">\n{data}\n</script>'


def sitemap(base_url, pages):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
             'xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for slug in pages:
        if slug == "tesekkurler":
            continue
        for lang in LANGS:
            lines.append("<url>")
            lines.append(f"<loc>{base_url}{page_url(lang, slug)}</loc>")
            for alt in LANGS:
                lines.append(
                    f'<xhtml:link rel="alternate" hreflang="{alt}" href="{base_url}{page_url(alt, slug)}"/>'
                )
            lines.append("</url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def write_manifest(out):
    entries = []
    for path in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256"):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{digest}  {path.relative_to(out).as_posix()}")
    (out / "MANIFEST.sha256").write_text("\n".join(entries) + "\n", encoding="utf-8")


def prune_fonts(fonts_dir, css_text):
    """Temanin stil dosyasinin kullanmadigi yazi tiplerini ve lisans dosyalarini ciktiya koyma."""
    used = set()
    for font in sorted(fonts_dir.glob("*.woff2")):
        if font.name in css_text:
            used.add(font.name.rsplit("-latin", 1)[0])
        else:
            font.unlink()
    for lic in sorted(fonts_dir.glob("LICENSE-*.txt")):
        if lic.name[len("LICENSE-"):-len(".txt")] not in used:
            lic.unlink()


def build(theme, out, base_url, noindex):
    tdir = SITE / "themes" / theme
    if not tdir.is_dir():
        raise BuildError(f"tema yok: {theme}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(SITE / "assets", out / "assets")
    shutil.copyfile(SITE / "base.css", out / "assets" / "base.css")
    shutil.copyfile(tdir / "style.css", out / "assets" / "style.css")
    prune_fonts(out / "assets" / "fonts", read(tdir / "style.css"))

    errors = []
    pages = ("index",) + SHARED_PAGES
    layout = read(tdir / "layout.html")
    for lang in LANGS:
        strings = json.loads(read(SITE / "i18n" / f"{lang}.json"))
        other = "en" if lang == "tr" else "tr"
        for slug in pages:
            where = f"{theme}/{lang}/{slug}"
            src = tdir / "index.html" if slug == "index" else SITE / "pages" / f"{slug}.html"
            title_key = "meta_title" if slug == "index" else f"page_{slug}_title"
            desc_key = "meta_description" if slug == "index" else f"page_{slug}_desc"
            ctx = {
                "lang": lang,
                "og_locale": "tr_TR" if lang == "tr" else "en_US",
                "home": page_url(lang, "index"),
                "kvkk_href": page_url(lang, "kvkk"),
                "cerez_href": page_url(lang, "cerez"),
                "canonical": base_url + page_url(lang, slug),
                "alt_tr": base_url + page_url("tr", slug),
                "alt_en": base_url + page_url("en", slug),
                "other_lang": other,
                "other_href": page_url(other, slug),
                "title": strings.get(title_key, ""),
                "description": strings.get(desc_key, ""),
                "robots_meta_html": '<meta name="robots" content="noindex, nofollow">' if noindex else "",
                "scripts_html": {"index": '<script src="/assets/failover.js" defer></script>',
                                 "demo": '<script src="/assets/demo.js" defer></script>'}.get(slug, ""),
                "jsonld_html": jsonld(base_url, strings) if slug == "index" else "",
                "toplayici_sha256": hashlib.sha256((SITE / "assets" / "alig-toplayici.py").read_bytes()).hexdigest(),
                "katalog_sha256": hashlib.sha256((SITE / "assets" / "sorgu-katalogu.txt").read_bytes()).hexdigest(),
            }
            if title_key not in strings or desc_key not in strings:
                errors.append(f"{where}: baslik/aciklama anahtari yok ({title_key}, {desc_key})")
                continue
            ctx["body_html"] = render(read(src), ctx, strings, errors, where)
            page = render(layout, ctx, strings, errors, where)
            target = out_file(out, lang, slug)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page, encoding="utf-8")

    if errors:
        raise BuildError("\n".join(sorted(set(errors))))

    robots = "User-agent: *\nDisallow: /\n" if noindex else f"User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n"
    (out / "robots.txt").write_text(robots, encoding="utf-8")
    if not noindex:
        (out / "sitemap.xml").write_text(sitemap(base_url, pages), encoding="utf-8")
    write_manifest(out)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--theme", default="all", choices=THEMES + ("all",))
    ap.add_argument("--out", default=None, help="tek tema icin cikti dizini (varsayilan dist/<tema>)")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--noindex", action="store_true", help="hazirlik ortami: noindex ve robots Disallow")
    args = ap.parse_args(argv)

    base_url = args.base_url or json.loads(read(SITE / "site.json"))["base_url"]
    base_url = base_url.rstrip("/")
    themes = THEMES if args.theme == "all" else (args.theme,)
    if args.out and len(themes) > 1:
        ap.error("--out yalnizca tek tema ile kullanilir")
    try:
        for theme in themes:
            out = Path(args.out) if args.out else ROOT / "dist" / theme
            build(theme, out, base_url, args.noindex)
            print(f"tamam: {theme} -> {out}")
    except BuildError as exc:
        print(f"DERLEME HATASI:\n{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

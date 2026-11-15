"""Maintenance mode (ALIG-OPS-002, decision OPS-K1). Standard library only. OFF by default: ALIG_BAKIM=1.

While on, every POST of the form, scan (upload, report delete/verify, Mode B), portal and admin services is answered
with 503 + Retry-After and a bilingual page, before anything is parsed or written. Reads (reports, admin pages), static
files (served by nginx) and /healthz stay open. The flag is read once at start; change /etc/alig/env and restart the
services to switch it (the write freeze of the PostgreSQL cutover, docs/postgresql-gecis.md section 9).
The page uses only the site's own stylesheets: no inline script or style, no external resource (CSP).
"""
import re
from html import escape

BEKLE_VARSAYILAN = 300   # seconds, the Retry-After value
BEKLE_EN_COK = 86400

M = {
    "tr": {"baslik": "Bakım çalışması", "ust": "alig.tech",
           "lead": "Sitenin yazma işlemleri bakım nedeniyle geçici olarak kapalı.",
           "ne": "Ne yapmalı",
           "ne_metin": "Formu, dosya yüklemeyi ve hesap işlemlerini biraz sonra yeniden deneyin. Gönderdiğiniz hiçbir şey kaydedilmedi. "
                       "Mevcut raporlarınız ve site sayfaları etkilenmez.",
           "geri": "Ana sayfaya dön"},
    "en": {"baslik": "Maintenance in progress", "ust": "alig.tech",
           "lead": "Write actions on the site are temporarily closed for maintenance.",
           "ne": "What to do",
           "ne_metin": "Please try the form, file upload and account actions again shortly. Nothing you sent was saved. "
                       "Your existing reports and the site pages are not affected.",
           "geri": "Back to the home page"},
}


def etkin(ortam):
    """True only for ALIG_BAKIM=1 (the same strict rule as the other gates)."""
    return ortam.get("ALIG_BAKIM") == "1"


def bekle_sn(ortam):
    """Retry-After seconds from ALIG_BAKIM_BEKLE_SN (1..86400); ValueError if it is not a plain integer in range."""
    ham = ortam.get("ALIG_BAKIM_BEKLE_SN")
    if ham is None:
        return BEKLE_VARSAYILAN
    if not ham.isascii() or not ham.isdigit() or not 1 <= int(ham) <= BEKLE_EN_COK:
        raise ValueError("ALIG_BAKIM_BEKLE_SN must be a whole number of seconds between 1 and %d" % BEKLE_EN_COK)
    return int(ham)


def ayarla(ortam, H):
    """Applies the environment to a handler class (H.bakim, H.bakim_bekle). True if maintenance mode is on."""
    H.bakim_bekle = bekle_sn(ortam)
    H.bakim = etkin(ortam)
    return H.bakim


def dil_sec(referer):
    """English if the request came from an /en/ page, otherwise Turkish."""
    return "en" if re.match(r"^https?://[^/]+/en(/|$)", referer or "") else "tr"


def sayfa(dil):
    d = dil if dil in M else "tr"
    m = M[d]
    kok = "/en/" if d == "en" else "/"
    return ("<!doctype html>\n<html lang=\"%s\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex,nofollow\"><title>%s | alig.tech</title>"
            "<link rel=\"stylesheet\" href=\"/assets/base.css\"><link rel=\"stylesheet\" href=\"/assets/style.css\"></head><body>"
            "<header class=\"top\"><div class=\"wrap\"><a class=\"brand\" href=\"%s\"><img src=\"/assets/logo.svg\" width=\"176\" height=\"36\" alt=\"alig.tech\"></a></div></header>"
            "<main id=\"main\"><article class=\"wrap prose tarama-page\"><p class=\"fine\">%s</p><h1>%s</h1><p class=\"lead\">%s</p>"
            "<h2>%s</h2><p>%s</p><p><a class=\"btn\" href=\"%s\">%s</a></p></article></main></body></html>\n") % (
        d, escape(m["baslik"]), kok, escape(m["ust"]), escape(m["baslik"]), escape(m["lead"]), escape(m["ne"]), escape(m["ne_metin"]),
        kok, escape(m["geri"]))


def engelle(h):
    """If maintenance mode is on, answers the request with the 503 page and returns True; the caller must stop."""
    if not getattr(h, "bakim", False):
        return False
    dil = dil_sec(h.headers.get("Referer"))
    h._send(503, sayfa(dil).encode("utf-8"), "text/html; charset=utf-8", extra=(("Retry-After", str(h.bakim_bekle)),))
    return True

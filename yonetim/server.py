#!/usr/bin/env python3
"""alig.tech yonetim paneli. Yalnizca standart kutuphane, sunucuda uretilen HTML, JavaScript yok.

Giris: kullanici + parola (scrypt) + dogrulama kodu (TOTP). Oturum cerezi HttpOnly, SameSite=Strict.
Her POST'ta CSRF kodu ve Origin denetimi. Tum yonetici islemleri SHA-256 zincirli denetim kaydina yazilir.
Yalniz 127.0.0.1'de dinler; disariya nginx (IP izin listesi) ya da SSH tuneli ile acilir.
"""
import argparse
import csv
import io
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
from tarama import depo as tdepo, kurallar, rapor as trapor  # noqa: E402
from yonetim import depo  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    TR = ZoneInfo("Europe/Istanbul")
except Exception:  # tzdata yoksa sabit UTC+3
    TR = timezone(timedelta(hours=3))

GOVDE_SINIRI = 8192
ONEM_AD = {"kritik": "Kritik", "yuksek": "Yüksek", "orta": "Orta", "dusuk": "Düşük", "bilgi": "Bilgi"}
DURUM_AD = {"yeni": "Yeni", "gorusuluyor": "Görüşülüyor", "kapandi": "Kapandı"}
DB_AD = {"pg": "PostgreSQL", "ms": "SQL Server", "my": "MySQL", "multi": "Birden çok", "unsure": "Emin değil"}
FIRMA_DURUM_AD = {"aktif": "Aktif", "pasif": "Pasif"}
KAYNAK_AD = {"tarama": "Sağlık taraması", "talep": "İletişim talebi"}
MENU = (("/yonetim/", "Özet"), ("/yonetim/firmalar", "Firmalar"), ("/yonetim/talepler", "Talepler"), ("/yonetim/taramalar", "Taramalar"),
        ("/yonetim/denetim", "Denetim kaydı"), ("/yonetim/sistem", "Sistem"))


def ist(utc):
    try:
        return datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(TR).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return "-"


def e(v):
    return escape("" if v is None else str(v))


def tablo(basliklar, satirlar, bos="Kayıt yok."):
    if not satirlar:
        return "<p class=\"muted\">%s</p>" % e(bos)
    return "<div class=\"scroll\"><table class=\"adm\"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>" % (
        "".join("<th scope=\"col\">%s</th>" % e(b) for b in basliklar), "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % h for h in s) for s in satirlar))


def ro(yol):
    """Salt okunur baglanti; dosya yoksa None."""
    if not Path(yol).exists():
        return None
    return sqlite3.connect("file:%s?mode=ro" % yol, uri=True)


def csv_hucre(v):
    """Hucre tablolama programinda formul olarak calismasin: =, +, -, @ ile baslayan degerin onune tek tirnak konur."""
    m = "" if v is None else str(v)
    m = m.replace("\r", " ").replace("\n", " ")
    return "'" + m if m[:1] in ("=", "+", "-", "@", "\t") else m


class H(BaseHTTPRequestHandler):
    ydb = "yonetim.sqlite"
    form_db = "form.sqlite"
    tarama_db = "tarama.sqlite"
    yedek_dizini = ""
    guvenli_cerez = True
    form_portu = 8090
    tarama_portu = 8091
    sys_version = ""

    # ---- altyapi ----
    def log_message(self, fmt, *a):
        print(self.command, self.path.split("?")[0], a[1] if len(a) > 1 else "", flush=True)

    @property
    def cerez_adi(self):
        return "__Host-alig_oturum" if self.guvenli_cerez else "alig_oturum"

    def _send(self, kod, govde=b"", ctype="text/html; charset=utf-8", extra=()):
        self.send_response(kod)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(govde)

    def _yonlendir(self, yol, extra=()):
        self._send(303, extra=(("Location", yol),) + tuple(extra))

    def _ip(self):
        return self.headers.get("X-Real-IP") or self.client_address[0]

    def _cerez(self):
        try:
            c = SimpleCookie(self.headers.get("Cookie") or "")
            return c[self.cerez_adi].value if self.cerez_adi in c else None
        except Exception:
            return None

    def _cerez_yaz(self, deger, sil=False):
        parca = ["%s=%s" % (self.cerez_adi, "" if sil else deger), "Path=/", "HttpOnly", "SameSite=Strict"]
        if self.guvenli_cerez:
            parca.append("Secure")
        if sil:
            parca.append("Max-Age=0")
        return ("Set-Cookie", "; ".join(parca))

    def _sayfa(self, baslik, icerik, oturum=None, kod=200):
        menu = ""
        if oturum:
            yol = urlparse(self.path).path
            menu = "<nav class=\"adm-nav\" aria-label=\"Yönetim\">%s<form method=\"post\" action=\"/yonetim/cikis\"><input type=\"hidden\" name=\"csrf\" value=\"%s\"><button class=\"linkbtn\" type=\"submit\">Çıkış (%s)</button></form></nav>" % (
                "".join("<a href=\"%s\"%s>%s</a>" % (h, " aria-current=\"page\"" if (yol == h or (h != "/yonetim/" and yol.startswith(h))) else "", e(a)) for h, a in MENU),
                e(oturum["csrf"]), e(oturum["ad"]))
        html = ("<!doctype html>\n<html lang=\"tr\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                "<meta name=\"robots\" content=\"noindex,nofollow\"><title>%s | alig.tech yönetim</title>"
                "<link rel=\"stylesheet\" href=\"/assets/base.css\"><link rel=\"stylesheet\" href=\"/assets/style.css\"><link rel=\"stylesheet\" href=\"/assets/yonetim.css\"></head>"
                "<body class=\"adm-body\"><header class=\"top\"><div class=\"wrap\"><a class=\"brand\" href=\"/yonetim/\"><img src=\"/assets/logo.svg\" width=\"176\" height=\"36\" alt=\"alig.tech\"></a><span class=\"adm-tag\">Yönetim</span></div></header>"
                "%s<main id=\"main\" class=\"wrap adm\"><h1>%s</h1>%s</main></body></html>\n") % (e(baslik), menu, e(baslik), icerik)
        self._send(kod, html.encode("utf-8"))

    def _form(self):
        try:
            n = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        if n < 0 or n > GOVDE_SINIRI or (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/x-www-form-urlencoded":
            return None
        return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True).items()}

    def _origin_ok(self):
        o = self.headers.get("Origin")
        return o is None or urlparse(o).netloc == (self.headers.get("Host") or "")

    # ---- yonlendirme ----
    def do_GET(self):
        u = urlparse(self.path)
        yol, q = u.path, parse_qs(u.query)
        if yol.startswith("/assets/"):
            return self._statik(yol)
        if not yol.startswith("/yonetim"):
            return self._send(404, b"yok\n", "text/plain; charset=utf-8")
        con = depo.baglan(self.ydb)
        try:
            if yol == "/yonetim/giris":
                return self._giris_sayfasi()
            o = depo.oturum(con, self._cerez())
            if not o:
                return self._yonlendir("/yonetim/giris")
            if yol in ("/yonetim", "/yonetim/"):
                return self._ozet(con, o)
            if yol == "/yonetim/firmalar":
                return self._firmalar(con, o, q)
            if yol == "/yonetim/firmalar.csv":
                return self._firmalar_csv(con, o, q)
            if yol == "/yonetim/talepler.csv":
                return self._talepler_csv(con, o, q)
            m = re.match(r"^/yonetim/firmalar/(\d{1,9})$", yol)
            if m:
                return self._firma(con, o, int(m.group(1)))
            if yol == "/yonetim/talepler":
                return self._talepler(con, o, q)
            if yol == "/yonetim/taramalar":
                return self._taramalar(con, o)
            m = re.match(r"^/yonetim/taramalar/(\d{1,9})$", yol)
            if m:
                return self._tarama(con, o, int(m.group(1)))
            if yol == "/yonetim/denetim":
                return self._denetim(con, o, q)
            if yol == "/yonetim/sistem":
                return self._sistem(con, o)
            self._sayfa("Bulunamadı", "<p>Bu sayfa yok.</p>", o, 404)
        finally:
            con.close()

    def do_POST(self):
        yol = urlparse(self.path).path
        if not yol.startswith("/yonetim/"):
            return self._send(404, b"yok\n", "text/plain; charset=utf-8")
        if not self._origin_ok():
            return self._send(403, b"kaynak reddedildi\n", "text/plain; charset=utf-8")
        f = self._form()
        if f is None:
            return self._send(400, b"gecersiz istek\n", "text/plain; charset=utf-8")
        con = depo.baglan(self.ydb)
        try:
            if yol == "/yonetim/giris":
                kod, _ = depo.giris(con, f.get("ad"), f.get("parola"), f.get("kod"), self._ip())
                if not kod:
                    return self._giris_sayfasi("Giriş başarısız. Bilgileri denetleyin ya da 15 dakika sonra yeniden deneyin.", 401)
                depo.temizle(con)
                return self._yonlendir("/yonetim/", (self._cerez_yaz(kod),))
            o = depo.oturum(con, self._cerez())
            if not o:
                return self._yonlendir("/yonetim/giris")
            if not f.get("csrf") or f["csrf"] != o["csrf"]:
                depo.denetim_ekle(con, o["ad"], "CSRF kodu uyusmadi: %s" % yol[:60])
                return self._send(403, b"gecersiz form kodu\n", "text/plain; charset=utf-8")
            if yol == "/yonetim/cikis":
                depo.cikis(con, self._cerez())
                depo.denetim_ekle(con, o["ad"], "cikis yapildi")
                return self._yonlendir("/yonetim/giris", (self._cerez_yaz("", sil=True),))
            m = re.match(r"^/yonetim/talepler/(\d{1,9})/durum$", yol)
            if m:
                if f.get("durum") not in depo.DURUMLAR:
                    return self._send(422, b"gecersiz durum\n", "text/plain; charset=utf-8")
                depo.talep_durum_yaz(con, int(m.group(1)), f["durum"], f.get("aciklama", ""), o["ad"])
                return self._yonlendir("/yonetim/talepler")
            m = re.match(r"^/yonetim/firmalar/(\d{1,9})/(durum|not|sinir|sil|izin)$", yol)
            if m:
                return self._firma_islem(con, o, int(m.group(1)), m.group(2), f)
            m = re.match(r"^/yonetim/taramalar/(\d{1,9})/sil$", yol)
            if m:
                tcon = tdepo.baglan(self.tarama_db)
                try:
                    n = tdepo.rapor_sil_id(tcon, int(m.group(1)))
                    tdepo.denetim_ekle(tcon, "yonetici:" + o["ad"], "rapor silindi #%s" % m.group(1) if n else "silme: rapor yok #%s" % m.group(1))
                finally:
                    tcon.close()
                depo.denetim_ekle(con, o["ad"], "tarama raporu silindi #%s" % m.group(1))
                return self._yonlendir("/yonetim/taramalar")
            self._send(404, b"yok\n", "text/plain; charset=utf-8")
        finally:
            con.close()

    def _statik(self, yol):
        """SSH tuneli kipinde stil ve logo: yalniz paketteki site/assets, yalniz bilinen turler."""
        turler = {".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2"}
        kok = (KOK / "site" / "assets").resolve()
        hedef = (kok / yol[len("/assets/"):]).resolve()
        if hedef.suffix not in turler or kok not in hedef.parents or not hedef.is_file():
            return self._send(404, b"yok\n", "text/plain; charset=utf-8")
        self._send(200, hedef.read_bytes(), turler[hedef.suffix])

    # ---- sayfalar ----
    def _giris_sayfasi(self, hata=None, kod=200):
        self._sayfa("Giriş", ("<p class=\"err\" role=\"alert\">%s</p>" % e(hata) if hata else "") +
                    "<form class=\"form adm-login\" method=\"post\" action=\"/yonetim/giris\" autocomplete=\"off\">"
                    "<div class=\"field field-wide\"><label for=\"g-ad\">Kullanıcı adı</label><input id=\"g-ad\" name=\"ad\" type=\"text\" required maxlength=\"32\" autocomplete=\"username\"></div>"
                    "<div class=\"field field-wide\"><label for=\"g-p\">Parola</label><input id=\"g-p\" name=\"parola\" type=\"password\" required maxlength=\"200\" autocomplete=\"current-password\"></div>"
                    "<div class=\"field field-wide\"><label for=\"g-k\">Doğrulama kodu (6 hane)</label><input id=\"g-k\" name=\"kod\" type=\"text\" inputmode=\"numeric\" pattern=\"[0-9 ]{6,7}\" required maxlength=\"7\" autocomplete=\"one-time-code\"></div>"
                    "<p><button class=\"btn\" type=\"submit\">Giriş yap</button></p></form>", None, kod)

    def _talep_satirlari(self):
        c = ro(self.form_db)
        if not c:
            return []
        try:
            return c.execute("SELECT id, created_utc, name, company, email, db, message FROM contact ORDER BY id DESC LIMIT 500").fetchall()
        except sqlite3.Error:
            return []
        finally:
            c.close()

    def _raporlar(self):
        if not Path(self.tarama_db).exists():
            return []
        c = tdepo.baglan(self.tarama_db)
        try:
            return tdepo.rapor_listele(c)
        finally:
            c.close()

    def _saglik(self, port, yol):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, yol), timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def _ozet(self, con, o):
        talepler = self._talep_satirlari()
        durumlar = depo.talep_durumlari(con)
        yeni = [t for t in talepler if durumlar.get(t[0], {}).get("durum", "yeni") == "yeni"]
        hafta = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        raporlar = self._raporlar()
        sayim = {k: 0 for k in kurallar.ONEM}
        for r in raporlar:
            for b in kurallar.degerlendir(r["belge"])[0]:
                sayim[b["onem"]] += 1
        zincir_t, red, kull, firma_n, pasif_n = "veritabanı yok", 0, 0, 0, 0
        if Path(self.tarama_db).exists():
            tc = tdepo.baglan(self.tarama_db)
            try:
                zd = tdepo.denetim_durum(tc, tdepo.denetim_anahtari())
                bozuk = zd["bozuk"]
                zincir_t = tdepo.denetim_metni(zd).replace("sağlam (anahtarsız kayıtlar)", "sağlam")
                red = tc.execute("SELECT count(*) FROM denetim WHERE olay LIKE 'sirket siniri asildi%'").fetchone()[0]
                kull = tc.execute("SELECT count(DISTINCT anahtar_sha256) FROM kullanim").fetchone()[0]
                self._firma_esitle(tc)
                firma_n = tc.execute("SELECT count(*) FROM firma").fetchone()[0]
                pasif_n = tc.execute("SELECT count(*) FROM firma WHERE durum='pasif'").fetchone()[0]
            finally:
                tc.close()
        yb = depo.denetim_dogrula(con, tdepo.denetim_anahtari())
        kutu = lambda ad, deger, alt="", kotu=False: "<div class=\"stat%s\"><p class=\"stat-k\">%s</p><p class=\"stat-v\">%s</p><p class=\"stat-s\">%s</p></div>" % (" bad" if kotu else "", e(ad), e(deger), e(alt))  # noqa: E731
        ic = "<div class=\"stats\">" + "".join([
            kutu("Kayıtlı firma", firma_n, "aktif %d, pasif %d" % (firma_n - pasif_n, pasif_n)),
            kutu("Yeni talep", len(yeni), "toplam %d, son 7 gün %d" % (len(talepler), len([t for t in talepler if t[1] >= hafta]))),
            kutu("Etkin tarama raporu", len(raporlar), "son 7 gün %d" % len([r for r in raporlar if r["olusturma_utc"] >= hafta])),
            kutu("Kritik ve yüksek bulgu", sayim["kritik"] + sayim["yuksek"], "kritik %d, yüksek %d" % (sayim["kritik"], sayim["yuksek"])),
            kutu("Tarama yapan şirket (30 gün)", kull, "sınır nedeniyle reddedilen %d" % red),
            kutu("Tarama denetim zinciri", zincir_t, kotu=not zincir_t.startswith("sağlam") and zincir_t != "veritabanı yok"),
            kutu("Yönetim denetim zinciri", "sağlam" if yb is None else "KIRIK: kayıt #%d" % yb, kotu=yb is not None),
            kutu("İletişim servisi", "çalışıyor" if self._saglik(self.form_portu, "/healthz") else "YANIT YOK", kotu=not self._saglik(self.form_portu, "/healthz")),
            kutu("Tarama servisi", "çalışıyor" if self._saglik(self.tarama_portu, "/api/tarama/saglik") else "YANIT YOK", kotu=not self._saglik(self.tarama_portu, "/api/tarama/saglik")),
        ]) + "</div>"
        ic += "<h2>Bekleyen talepler</h2>" + tablo(["Zaman", "Ad", "Şirket", "Veritabanı"], [[e(ist(t[1])), e(t[2]), e(t[3]), e(DB_AD.get(t[5], t[5]))] for t in yeni[:8]], "Bekleyen talep yok.")
        ic += "<p><a href=\"/yonetim/talepler\">Tüm talepler</a></p>"
        self._sayfa("Özet", ic, o)

    # ---- firmalar ----
    def _firma_esitle(self, tc):
        """Iletisim formundan gelen sirketleri firma kaydina ekler (var olani degistirmez)."""
        for tid, zaman, ad, sirket, eposta, _db, _msg in self._talep_satirlari():
            anahtar = tdepo.firma_anahtari(eposta or "")
            if anahtar:
                tdepo.firma_kaydet(tc, anahtar, sirket, eposta, "talep", zaman=zaman, guncelle=False)

    def _talep_sayilari(self):
        say = {}
        for t_ in self._talep_satirlari():
            a = tdepo.firma_anahtari(t_[4] or "")
            if a:
                say.setdefault(a, []).append(t_)
        return say

    def _durum_dugmesi(self, f, o, donus):
        hedef = "pasif" if f["durum"] == "aktif" else "aktif"
        return ("<form method=\"post\" action=\"/yonetim/firmalar/%d/durum\" class=\"inline\"><input type=\"hidden\" name=\"csrf\" value=\"%s\">"
                "<input type=\"hidden\" name=\"durum\" value=\"%s\"><input type=\"hidden\" name=\"donus\" value=\"%s\">"
                "<button class=\"btn btn-sm%s\" type=\"submit\">%s</button></form>") % (
                    f["id"], e(o["csrf"]), hedef, donus, " btn-ghost" if hedef == "pasif" else "", "Pasif et" if hedef == "pasif" else "Aktif et")

    def _firma_suz(self, q):
        """(tum firmalar, suzulmus firmalar, ara, durum) dondurur."""
        tc = tdepo.baglan(self.tarama_db)
        try:
            self._firma_esitle(tc)
            firmalar = tdepo.firma_listele(tc)
        finally:
            tc.close()
        suz = (q.get("durum") or [""])[0]
        suz = suz if suz in tdepo.FIRMA_DURUMLARI else ""
        ara = (q.get("ara") or [""])[0].strip().lower()[:80]
        secili = [f for f in firmalar
                  if (not suz or f["durum"] == suz)
                  and (not ara or ara in f["ad"].lower() or ara in f["anahtar"] or ara in f["eposta"])]
        return firmalar, secili, ara, suz

    def _csv(self, dosya_adi, baslik, satirlar):
        tampon = io.StringIO()
        yaz = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
        yaz.writerow(baslik)
        for s in satirlar:
            yaz.writerow([csv_hucre(v) for v in s])
        self._send(200, ("\ufeff" + tampon.getvalue()).encode("utf-8"), "text/csv; charset=utf-8",
                   extra=(("Content-Disposition", "attachment; filename=\"%s\"" % dosya_adi),))

    def _firmalar_csv(self, con, o, q):
        _, secili, _, _ = self._firma_suz(q)
        talepler = self._talep_sayilari()
        satirlar = [[f["ad"], f["anahtar"], f["eposta"], FIRMA_DURUM_AD[f["durum"]], f["rapor_sayisi"], len(talepler.get(f["anahtar"], [])),
                     KAYNAK_AD.get(f["kaynak"], f["kaynak"]), f["kayit_utc"], f["son_utc"], f["aciklama"]] for f in secili]
        depo.denetim_ekle(con, o["ad"], "firmalar csv indirildi, %d satir" % len(satirlar))
        self._csv("alig-firmalar.csv", ["Firma", "Alan adı ya da adres", "E-posta", "Durum", "Tarama", "Talep", "İlk kaynak",
                                        "Kayıt (UTC)", "Son etkinlik (UTC)", "Not"], satirlar)

    def _talepler_csv(self, con, o, q):
        durumlar = depo.talep_durumlari(con)
        suz = (q.get("durum") or [""])[0]
        satirlar = []
        for t in self._talep_satirlari():
            d = durumlar.get(t[0], {"durum": "yeni", "aciklama": ""})
            if suz in depo.DURUMLAR and d["durum"] != suz:
                continue
            satirlar.append([t[1], t[2], t[3], t[4], DB_AD.get(t[5], t[5]), t[6], DURUM_AD[d["durum"]], d["aciklama"]])
        depo.denetim_ekle(con, o["ad"], "talepler csv indirildi, %d satir" % len(satirlar))
        self._csv("alig-talepler.csv", ["Zaman (UTC)", "Kişi", "Şirket", "E-posta", "Veritabanı", "Mesaj", "Durum", "Not"], satirlar)

    def _firmalar(self, con, o, q):
        firmalar, secili, ara, suz = self._firma_suz(q)
        talepler = self._talep_sayilari()
        satirlar = []
        for f in secili:
            satirlar.append(["<a href=\"/yonetim/firmalar/%d\"><strong>%s</strong></a><br><span class=\"muted\">%s</span>" % (f["id"], e(f["ad"] or "(adsız)"), e(f["anahtar"])),
                             "<a href=\"mailto:%s\">%s</a>" % (e(f["eposta"]), e(f["eposta"])),
                             "<span class=\"pill pill-%s\">%s</span>" % (f["durum"], e(FIRMA_DURUM_AD[f["durum"]])),
                             e(f["rapor_sayisi"]), e(len(talepler.get(f["anahtar"], []))), e(KAYNAK_AD.get(f["kaynak"], f["kaynak"])),
                             e(ist(f["kayit_utc"])), e(ist(f["son_utc"])), self._durum_dugmesi(f, o, "liste")])
        ust = ("<form method=\"get\" action=\"/yonetim/firmalar\" class=\"inline searchbar\"><label class=\"vh\" for=\"ara\">Ara</label>"
               "<input id=\"ara\" name=\"ara\" type=\"text\" maxlength=\"80\" value=\"%s\" placeholder=\"Firma adı, alan adı ya da e-posta\">"
               "<button class=\"btn btn-sm\" type=\"submit\">Ara</button></form>") % e(ara)
        ust += "<p class=\"filters\">Süz: <a href=\"/yonetim/firmalar\">Tümü (%d)</a> <a href=\"/yonetim/firmalar?durum=aktif\">Aktif (%d)</a> <a href=\"/yonetim/firmalar?durum=pasif\">Pasif (%d)</a></p>" % (
            len(firmalar), sum(1 for f in firmalar if f["durum"] == "aktif"), sum(1 for f in firmalar if f["durum"] == "pasif"))
        ust += "<p><a class=\"textlink\" href=\"/yonetim/firmalar.csv?%s\">Bu listeyi CSV olarak indir</a></p>" % e(urlencode({"ara": ara, "durum": suz}))
        depo.denetim_ekle(con, o["ad"], "firmalar goruntulendi")
        self._sayfa("Firmalar", ust + tablo(["Firma", "E-posta", "Durum", "Tarama", "Talep", "İlk kaynak", "Kayıt", "Son etkinlik", "İşlem"], satirlar, "Firma kaydı yok."), o)

    def _firma(self, con, o, fid):
        tc = tdepo.baglan(self.tarama_db)
        try:
            f = tdepo.firma_getir(tc, fid)
            if not f:
                return self._sayfa("Bulunamadı", "<p>Firma yok.</p>", o, 404)
            raporlar = tdepo.rapor_listele(tc, firma_id=fid)
            kalan = max(0, tdepo.SINIR_ADET - tdepo.kullanim_say(tc, tdepo.sirket_anahtari(f["eposta"]) or ""))
        finally:
            tc.close()
        depo.denetim_ekle(con, o["ad"], "firma goruntulendi #%d" % fid)
        csrf = e(o["csrf"])
        ic = "<p><a href=\"/yonetim/firmalar\">Firmalara dön</a></p>"
        ic += ("<dl class=\"facts\"><dt>Durum</dt><dd><span class=\"pill pill-%s\">%s</span></dd><dt>Tanımlayıcı</dt><dd>%s</dd><dt>E-posta</dt><dd><a href=\"mailto:%s\">%s</a></dd>"
               "<dt>İlk kaynak</dt><dd>%s</dd><dt>Kayıt</dt><dd>%s</dd><dt>Son etkinlik</dt><dd>%s</dd><dt>Kalan ücretsiz tarama</dt><dd>%d / %d (30 gün)</dd></dl>") % (
                   f["durum"], e(FIRMA_DURUM_AD[f["durum"]]), e(f["anahtar"]), e(f["eposta"]), e(f["eposta"]), e(KAYNAK_AD.get(f["kaynak"], f["kaynak"])),
                   e(ist(f["kayit_utc"])), e(ist(f["son_utc"])), kalan, tdepo.SINIR_ADET)
        ic += "<h2>İşlemler</h2><div class=\"actions\">" + self._durum_dugmesi(f, o, "detay")
        ic += ("<form method=\"post\" action=\"/yonetim/firmalar/%d/sinir\" class=\"inline\"><input type=\"hidden\" name=\"csrf\" value=\"%s\">"
               "<button class=\"btn btn-sm btn-ghost\" type=\"submit\">Tarama hakkını sıfırla</button></form>") % (fid, csrf)
        ic += ("<form method=\"post\" action=\"/yonetim/firmalar/%d/izin\" class=\"inline\"><input type=\"hidden\" name=\"csrf\" value=\"%s\">"
               "<input type=\"hidden\" name=\"izin\" value=\"%s\"><button class=\"btn btn-sm btn-ghost\" type=\"submit\">%s</button></form></div>") % (
                   fid, csrf, "0" if f["dogrudan_izin"] else "1", "Doğrudan bağlantı iznini kaldır" if f["dogrudan_izin"] else "Doğrudan bağlantı izni ver")
        ic += "<p class=\"muted\">Doğrudan bağlantı: <strong>%s</strong>. İzinli firma, bağlantı bilgisini vererek taramayı alig.tech sunucusundan çalıştırabilir. Yalnızca kimliğinden emin olduğunuz firmalara verin.</p>" % (
            "izinli" if f["dogrudan_izin"] else "izinsiz")
        ic += "<p class=\"muted\">Pasif firma yeni tarama yükleyemez. Mevcut raporları silinmez ve süreleri dolana kadar bağlantılarıyla açılır.</p>"
        ic += ("<form method=\"post\" action=\"/yonetim/firmalar/%d/not\" class=\"form notform\"><input type=\"hidden\" name=\"csrf\" value=\"%s\">"
               "<div class=\"field field-wide\"><label for=\"f-not\">Not</label><textarea id=\"f-not\" name=\"aciklama\" maxlength=\"500\" rows=\"3\">%s</textarea></div>"
               "<p><button class=\"btn btn-sm\" type=\"submit\">Notu kaydet</button></p></form>") % (fid, csrf, e(f["aciklama"]))
        rs = []
        for r in raporlar:
            b, ol = kurallar.degerlendir(r["belge"])
            rs.append(["<a href=\"/yonetim/taramalar/%d\">#%d</a>" % (r["id"], r["id"]), e(ist(r["olusturma_utc"])),
                       e(", ".join("%s %d" % (ONEM_AD[k], n) for k, n in ((k, sum(1 for x in b if x["onem"] == k)) for k in kurallar.ONEM) if n) or "bulgu yok"),
                       e(len(ol)), e(ist(r["bitis_utc"]))])
        ic += "<h2>Taramalar</h2>" + tablo(["Rapor", "Yüklenme", "Bulgular", "Ölçülemeyen", "Silinme"], rs, "Bu firmanın taraması yok.")
        durumlar = depo.talep_durumlari(con)
        ts = [[e(ist(t_[1])), e(t_[2]), "<a href=\"mailto:%s\">%s</a>" % (e(t_[4]), e(t_[4])), "<span class=\"msg\">%s</span>" % e(t_[6]),
               e(DURUM_AD[durumlar.get(t_[0], {}).get("durum", "yeni")])] for t_ in self._talep_sayilari().get(f["anahtar"], [])]
        ic += "<h2>İletişim talepleri</h2>" + tablo(["Zaman", "Kişi", "E-posta", "Mesaj", "Durum"], ts, "Bu firmadan talep yok.")
        ic += ("<h2>Firmayı sil</h2><form method=\"post\" action=\"/yonetim/firmalar/%d/sil\" class=\"inline danger\"><input type=\"hidden\" name=\"csrf\" value=\"%s\">"
               "<label for=\"f-emin\"><input id=\"f-emin\" type=\"checkbox\" name=\"emin\" value=\"evet\" required> Firma kaydını, %d tarama raporunu ve tarama sayımını kalıcı olarak sil. İletişim talepleri silinmez.</label>"
               "<button class=\"btn btn-sm btn-ghost\" type=\"submit\">Kalıcı olarak sil</button></form>") % (fid, csrf, len(raporlar))
        self._sayfa(f["ad"] or "(adsız firma)", ic, o)

    def _firma_islem(self, con, o, fid, islem, f):
        tc = tdepo.baglan(self.tarama_db)
        try:
            firma = tdepo.firma_getir(tc, fid)
            if not firma:
                return self._send(404, b"yok\n", "text/plain; charset=utf-8")
            if islem == "durum":
                if f.get("durum") not in tdepo.FIRMA_DURUMLARI:
                    return self._send(422, b"gecersiz durum\n", "text/plain; charset=utf-8")
                tdepo.firma_durum_yaz(tc, fid, f["durum"])
                olay = "firma #%d durumu: %s" % (fid, f["durum"])
            elif islem == "not":
                tdepo.firma_not_yaz(tc, fid, f.get("aciklama", ""))
                olay = "firma #%d notu guncellendi" % fid
            elif islem == "izin":
                if f.get("izin") not in ("0", "1"):
                    return self._send(422, b"gecersiz izin\n", "text/plain; charset=utf-8")
                tdepo.firma_izin_yaz(tc, fid, f["izin"] == "1")
                olay = "firma #%d dogrudan baglanti izni: %s" % (fid, "verildi" if f["izin"] == "1" else "kaldirildi")
            elif islem == "sinir":
                olay = "firma #%d tarama hakki sifirlandi (%d kayit)" % (fid, tdepo.firma_sinir_sifirla(tc, fid))
            else:
                if f.get("emin") != "evet":
                    return self._send(422, b"onay kutusu isaretlenmeli\n", "text/plain; charset=utf-8")
                olay = "firma #%d silindi (%d rapor)" % (fid, tdepo.firma_sil(tc, fid))
            tdepo.denetim_ekle(tc, "yonetici:" + o["ad"], olay)
        finally:
            tc.close()
        depo.denetim_ekle(con, o["ad"], olay)
        self._yonlendir("/yonetim/firmalar" if islem == "sil" or f.get("donus") == "liste" else "/yonetim/firmalar/%d" % fid)

    def _talepler(self, con, o, q):
        durumlar = depo.talep_durumlari(con)
        suz = (q.get("durum") or [""])[0]
        satirlar = []
        for t in self._talep_satirlari():
            d = durumlar.get(t[0], {"durum": "yeni", "aciklama": ""})
            if suz in depo.DURUMLAR and d["durum"] != suz:
                continue
            sec = "".join("<option value=\"%s\"%s>%s</option>" % (k, " selected" if k == d["durum"] else "", e(DURUM_AD[k])) for k in depo.DURUMLAR)
            form = ("<form method=\"post\" action=\"/yonetim/talepler/%d/durum\" class=\"inline\"><input type=\"hidden\" name=\"csrf\" value=\"%s\">"
                    "<label class=\"vh\" for=\"d-%d\">Durum</label><select id=\"d-%d\" name=\"durum\">%s</select>"
                    "<label class=\"vh\" for=\"n-%d\">Not</label><input id=\"n-%d\" name=\"aciklama\" type=\"text\" maxlength=\"500\" value=\"%s\" placeholder=\"Not\">"
                    "<button class=\"btn btn-sm\" type=\"submit\">Kaydet</button></form>") % (t[0], e(o["csrf"]), t[0], t[0], sec, t[0], t[0], e(d["aciklama"]))
            satirlar.append([e(ist(t[1])), "<strong>%s</strong><br>%s" % (e(t[2]), e(t[3])), "<a href=\"mailto:%s\">%s</a>" % (e(t[4]), e(t[4])),
                             e(DB_AD.get(t[5], t[5])), "<span class=\"msg\">%s</span>" % e(t[6]), form])
        suzgec = "<p class=\"filters\">Süz: <a href=\"/yonetim/talepler\">Tümü</a> " + " ".join("<a href=\"/yonetim/talepler?durum=%s\">%s</a>" % (k, e(v)) for k, v in DURUM_AD.items()) + "</p>"
        suzgec += "<p><a class=\"textlink\" href=\"/yonetim/talepler.csv?%s\">Bu listeyi CSV olarak indir</a></p>" % e(urlencode({"durum": suz if suz in depo.DURUMLAR else ""}))
        depo.denetim_ekle(con, o["ad"], "talepler goruntulendi")
        self._sayfa("Talepler", suzgec + tablo(["Zaman", "Kişi", "E-posta", "Veritabanı", "Mesaj", "Durum"], satirlar, "Talep yok."), o)

    def _taramalar(self, con, o):
        satirlar = []
        adlar = {}
        if Path(self.tarama_db).exists():
            tc = tdepo.baglan(self.tarama_db)
            try:
                adlar = {f["id"]: f["ad"] or f["anahtar"] for f in tdepo.firma_listele(tc)}
            finally:
                tc.close()
        for r in self._raporlar():
            b, ol = kurallar.degerlendir(r["belge"])
            ozet = ", ".join("%s %d" % (ONEM_AD[k], n) for k, n in ((k, sum(1 for x in b if x["onem"] == k)) for k in kurallar.ONEM) if n) or "bulgu yok"
            firma = "<a href=\"/yonetim/firmalar/%d\">%s</a>" % (r["firma_id"], e(adlar[r["firma_id"]])) if r.get("firma_id") in adlar else "<span class=\"muted\">bilinmiyor</span>"
            satirlar.append(["<a href=\"/yonetim/taramalar/%d\">#%d</a>" % (r["id"], r["id"]), firma, e(ist(r["olusturma_utc"])), e(r["motor"]), e(ozet), e(len(ol)),
                             e("evet" if r["belge"].get("maskeli") else "hayır"), e(ist(r["bitis_utc"]))])
        self._sayfa("Taramalar", "<p class=\"muted\">Raporlar 30 gün sonra kendiliğinden silinir.</p>" +
                    tablo(["Rapor", "Firma", "Yüklenme", "Motor", "Bulgular", "Ölçülemeyen", "Maskeli", "Silinme"], satirlar, "Tarama yok."), o)

    def _tarama(self, con, o, rid):
        if not Path(self.tarama_db).exists():
            return self._sayfa("Bulunamadı", "<p>Rapor yok.</p>", o, 404)
        tc = tdepo.baglan(self.tarama_db)
        try:
            r = tdepo.rapor_getir_id(tc, rid)
            if not r:
                return self._sayfa("Bulunamadı", "<p>Rapor yok.</p>", o, 404)
            tdepo.denetim_ekle(tc, "yonetici:" + o["ad"], "rapor goruntulendi #%d" % rid)  # musteri verisine erisim ayni zincirde
        finally:
            tc.close()
        depo.denetim_ekle(con, o["ad"], "tarama raporu goruntulendi #%d" % rid)
        govde, _, _ = trapor.govde(r, "tr", "", eylemler=False)
        govde = govde.replace("<article class=\"wrap prose report\">", "<article class=\"report adm-report\">").replace("<h1>", "<h2 class=\"vh\">").replace("</h1>", "</h2>", 1)
        sil = ("<form method=\"post\" action=\"/yonetim/taramalar/%d/sil\"><input type=\"hidden\" name=\"csrf\" value=\"%s\">"
               "<button class=\"btn btn-ghost\" type=\"submit\">Bu raporu kalıcı olarak sil</button></form>") % (rid, e(o["csrf"]))
        self._sayfa("Tarama raporu #%d" % rid, "<p><a href=\"/yonetim/taramalar\">Taramalara dön</a></p>" + govde + sil, o)

    def _denetim(self, con, o, q):
        kaynak = (q.get("kaynak") or ["tarama"])[0]
        kaynak = kaynak if kaynak in ("tarama", "yonetim") else "tarama"
        try:
            sayfa = max(1, min(int((q.get("sayfa") or ["1"])[0]), 100000))
        except ValueError:
            sayfa = 1
        satirlar, bozuk, toplam = [], None, 0
        zd = {"bozuk": None, "dogrulanamayan": 0, "anahtarli": False, "kayit": 0, "son": None}
        c = con if kaynak == "yonetim" else (tdepo.baglan(self.tarama_db) if Path(self.tarama_db).exists() else None)
        if c is not None:
            try:
                zd = tdepo.denetim_durum(c, tdepo.denetim_anahtari())
                bozuk = zd["bozuk"]
                toplam = c.execute("SELECT count(*) FROM denetim").fetchone()[0]
                for seq, z, ak, ol, oz in c.execute("SELECT seq, zaman_utc, aktor, olay, ozet FROM denetim ORDER BY seq DESC LIMIT 50 OFFSET ?", ((sayfa - 1) * 50,)):
                    satirlar.append([e(seq), e(ist(z)), e(ak), e(ol), "<code>%s</code>" % e(oz[:16])])
            finally:
                if c is not con:
                    c.close()
        durum = "<p class=\"%s\" role=\"status\">Zincir %s (%d kayıt).</p>" % ("ok" if bozuk is None else "err", "sağlam" if bozuk is None else "KIRIK: kayıt #%d" % bozuk, toplam)
        sekme = "<p class=\"filters\">Kaynak: <a href=\"/yonetim/denetim?kaynak=tarama\"%s>Sağlık taraması</a> <a href=\"/yonetim/denetim?kaynak=yonetim\"%s>Yönetim paneli</a></p>" % (
            " aria-current=\"page\"" if kaynak == "tarama" else "", " aria-current=\"page\"" if kaynak == "yonetim" else "")
        gez = "<p class=\"filters\">%s %s</p>" % (
            "<a href=\"/yonetim/denetim?kaynak=%s&amp;sayfa=%d\">Daha yeni</a>" % (kaynak, sayfa - 1) if sayfa > 1 else "",
            "<a href=\"/yonetim/denetim?kaynak=%s&amp;sayfa=%d\">Daha eski</a>" % (kaynak, sayfa + 1) if sayfa * 50 < toplam else "")
        self._sayfa("Denetim kaydı", sekme + durum + tablo(["#", "Zaman", "Aktör", "Olay", "Özet"], satirlar) + gez, o)

    def _sistem(self, con, o):
        surum = (KOK / "VERSION").read_text().strip() if (KOK / "VERSION").exists() else "geliştirme (paketlenmemiş)"
        dosyalar = []
        for ad, yol in (("İletişim formu", self.form_db), ("Sağlık taraması", self.tarama_db), ("Yönetim paneli", self.ydb)):
            p = Path(yol)
            dosyalar.append([e(ad), e(p.name), e("%.1f KB" % (p.stat().st_size / 1024) if p.exists() else "yok")])
        yedekler = []
        if self.yedek_dizini and Path(self.yedek_dizini).is_dir():
            for p in sorted(Path(self.yedek_dizini).glob("*.sqlite"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
                yedekler.append([e(p.name), e("%.1f KB" % (p.stat().st_size / 1024)),
                                 e(datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).astimezone(TR).strftime("%d.%m.%Y %H:%M"))])
        servis = [[e("İletişim formu (127.0.0.1:%d)" % self.form_portu), e("çalışıyor" if self._saglik(self.form_portu, "/healthz") else "YANIT YOK")],
                  [e("Sağlık taraması (127.0.0.1:%d)" % self.tarama_portu), e("çalışıyor" if self._saglik(self.tarama_portu, "/api/tarama/saglik") else "YANIT YOK")]]
        oturumlar = [[e(a), e(ist(z1)), e(ist(z2))] for a, z1, z2 in con.execute("SELECT ad, olusturma_utc, son_erisim_utc FROM oturum ORDER BY son_erisim_utc DESC")]
        ic = "<dl class=\"facts\"><dt>Sürüm</dt><dd>%s</dd><dt>Sunucu saati</dt><dd>%s (Europe/Istanbul)</dd></dl>" % (e(surum), e(datetime.now(TR).strftime("%d.%m.%Y %H:%M")))
        ic += "<h2>Servisler</h2>" + tablo(["Servis", "Durum"], servis)
        ic += "<h2>Veritabanları</h2>" + tablo(["Ad", "Dosya", "Boyut"], dosyalar)
        ic += "<h2>Yedekler</h2>" + tablo(["Dosya", "Boyut", "Zaman"], yedekler, "Yedek dizini tanımlı değil ya da boş.")
        ic += "<h2>Açık oturumlar</h2>" + tablo(["Kullanıcı", "Giriş", "Son erişim"], oturumlar)
        self._sayfa("Sistem", ic, o)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("ALIG_YONETIM_DB", "yonetim.sqlite"))
    ap.add_argument("--form-db", default="form.sqlite")
    ap.add_argument("--tarama-db", default="tarama.sqlite")
    ap.add_argument("--yedek", default="")
    ap.add_argument("--port", type=int, default=8092)
    ap.add_argument("--form-portu", type=int, default=8090)
    ap.add_argument("--tarama-portu", type=int, default=8091)
    ap.add_argument("--guvensiz-cerez", action="store_true", help="yalniz SSH tuneli ya da yerel deneme (HTTP) icin")
    a = ap.parse_args(argv)
    H.ydb, H.form_db, H.tarama_db, H.yedek_dizini = a.db, a.form_db, a.tarama_db, a.yedek
    H.form_portu, H.tarama_portu, H.guvenli_cerez = a.form_portu, a.tarama_portu, not a.guvensiz_cerez
    try:
        depo.zincir.denetim_anahtari()
    except depo.zincir.AnahtarHatasi as ex:
        raise SystemExit("hata: %s" % ex)
    depo.baglan(a.db).close()
    print("yonetim paneli dinliyor 127.0.0.1:%d" % a.port, flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()  # bilerek yalniz loopback


if __name__ == "__main__":
    main()

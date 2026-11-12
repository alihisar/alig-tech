#!/usr/bin/env python3
"""Saglik taramasi uc noktalari. Yalnizca standart kutuphane.

POST /api/tarama/yukle   multipart/form-data: dosya (toplama JSON), dil (tr|en), yetki (onay kutusu)
GET  /rapor/<token>/     rapor sayfasi
POST /rapor/<token>/sil  raporu hemen siler
Web sureci musteri veritabanina BAGLANMAZ; yalniz yuklenen dosyayi isler.
"""
import argparse
import email.parser
import email.policy
import os
import re
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import importlib.util  # noqa: E402

from tarama import baglanti, calistirici, depo, hata, hedef, rapor, saklama, yukleme  # noqa: E402

_spec = importlib.util.spec_from_file_location("alig_form_server", Path(__file__).resolve().parent.parent / "form" / "server.py")
_form = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_form)
RateLimiter = _form.RateLimiter

TOKEN = re.compile(r"^/rapor/([A-Za-z0-9_\-]{43})/(sil)?$")
ISTEK = re.compile(r"^/api/tarama/baglan/([A-Za-z0-9_\-]{43})$")
TARAMA_YUVASI = threading.BoundedSemaphore(2)   # ayni anda en cok iki dogrudan tarama
KILIT = threading.Lock()  # sinir sayimi ve ekleme birlikte yapilsin
GOVDE_SINIRI = yukleme.MAX_BAYT + 64 * 1024


def multipart(ctype, govde):
    """{alan: bytes}. email ayristiricisi ile; cgi modulu yeni surumlerde yok."""
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + govde)
    if not msg.is_multipart():
        return {}
    out = {}
    for parca in msg.iter_parts():
        ad = parca.get_param("name", header="content-disposition")
        if ad and ad not in out:
            out[ad] = parca.get_payload(decode=True) or b""
    return out


class H(BaseHTTPRequestHandler):
    db_yolu = "tarama.sqlite"
    sinir = RateLimiter(per_window=5)
    sirket_adet = depo.SINIR_ADET
    motorlar = ("postgresql",)  # SQL Server on surumu: ALIG_MSSQL=1 ile acilir
    dogrudan = False            # Kip B (dogrudan baglanti): ALIG_DOGRUDAN=1 ile acilir
    psql = "psql"
    sslmode = "require"
    yasak_aglar = ()            # kendi adres araliklarimiz: ALIG_YASAK_AGLAR
    hedef_dogrula = staticmethod(hedef.dogrula)
    tara = staticmethod(baglanti.tara)   # yalniz yerel gelistirme: calistirici_soketi yoksa surec ici
    calistirici_soketi = None            # uretimde zorunlu: tarama ayri calistirici surecinde kosar
    sys_version = ""

    def _send(self, kod, govde=b"", ctype="text/plain; charset=utf-8", extra=()):
        self.send_response(kod)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(govde)

    def _ip(self):
        return self.headers.get("X-Real-IP") or self.client_address[0]

    def _hata(self, kod, tur, dil=None, ayrinti=None, extra=()):
        """Musteriye gosterilen hata sayfasi. Dil formdan, yoksa Referer'dan cikar."""
        if dil not in ("tr", "en"):
            dil = "en" if "/en/" in (self.headers.get("Referer") or "") else "tr"
        self._send(kod, hata.sayfa(tur, dil, ayrinti).encode("utf-8"), "text/html; charset=utf-8", extra=extra)

    def do_GET(self):
        yol = self.path.split("?")[0]
        if yol == "/api/tarama/saglik":
            try:
                depo.baglan(self.db_yolu).close()
                return self._send(200, b"ok\n")
            except Exception:
                return self._send(503, b"db\n")
        if yol == "/api/tarama/baglan" and self.dogrudan:
            dil = (parse_qs(self.path.partition("?")[2]).get("dil") or ["tr"])[0]
            return self._send(200, hata.baglan_formu(dil).encode("utf-8"), "text/html; charset=utf-8")
        m = TOKEN.match(yol if yol.endswith("/") else yol + "/")
        if not m or m.group(2):
            return self._send(404, b"yok\n")
        con = depo.baglan(self.db_yolu)
        try:
            r = depo.rapor_getir(con, m.group(1))
            if not r:
                return self._send(404, b"yok\n")
            depo.denetim_ekle(con, "musteri", "rapor goruntulendi #%d" % r["id"])
            self._send(200, rapor.sayfa(r, r["dil"], m.group(1)).encode("utf-8"), "text/html; charset=utf-8")
        finally:
            con.close()

    def do_POST(self):
        yol = self.path.split("?")[0]
        m = TOKEN.match(yol)
        if m and m.group(2) == "sil":
            return self._sil(m.group(1))
        if self.dogrudan and yol == "/api/tarama/baglan":
            return self._baglan_baslat()
        mi = ISTEK.match(yol)
        if self.dogrudan and mi:
            return self._baglan_calistir(mi.group(1))
        if yol != "/api/tarama/yukle":
            return self._send(404, b"yok\n")
        ctype = self.headers.get("Content-Type") or ""
        if not ctype.lower().startswith("multipart/form-data"):
            return self._hata(415, "tur")
        try:
            uzunluk = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._hata(411, "tur")
        if uzunluk < 0 or uzunluk > GOVDE_SINIRI:
            return self._hata(413, "buyuk")
        if not self.sinir.allow(self._ip()):
            return self._hata(429, "hiz", extra=(("Retry-After", "3600"),))
        alanlar = multipart(ctype, self.rfile.read(uzunluk))
        dil = alanlar.get("dil", b"tr").decode("ascii", "replace")
        dil = dil if dil in ("tr", "en") else "tr"
        if alanlar.get("yetki", b"").strip() not in (b"on", b"1", b"evet", b"yes"):
            return self._hata(422, "yetki", dil)
        eposta = alanlar.get("eposta", b"").decode("utf-8", "replace")
        anahtar_s = depo.sirket_anahtari(eposta)
        if not anahtar_s:
            return self._hata(422, "eposta", dil)
        sirket = re.sub(r"[\x00-\x1f\x7f]", "", alanlar.get("sirket", b"").decode("utf-8", "replace")).strip()
        if not sirket or len(sirket) > 160:
            return self._hata(422, "sirket", dil)
        try:
            belge = yukleme.coz(alanlar.get("dosya", b""), self.motorlar)
        except yukleme.Gecersiz as e:
            tur, ayrinti = hata.dosya_hatasi(e.kod, e.ek, dil)
            return self._hata(422, tur, dil, ayrinti=ayrinti)
        anahtar = secrets.token_urlsafe(32)
        con = depo.baglan(self.db_yolu)
        try:
            firma = depo.firma_kaydet(con, depo.firma_anahtari(eposta), sirket, eposta, "tarama")
            if firma["durum"] != "aktif":
                depo.denetim_ekle(con, "sistem", "pasif firma yuklemesi reddedildi, firma #%d" % firma["id"])
                return self._hata(403, "pasif", dil)
            with KILIT:
                asildi = depo.kullanim_say(con, anahtar_s) >= self.sirket_adet
                if not asildi:
                    depo.kullanim_ekle(con, anahtar_s)
            if asildi:
                depo.denetim_ekle(con, "sistem", "sirket siniri asildi, istek reddedildi")
                return self._hata(429, "sinir", dil, extra=(("Retry-After", str(depo.SINIR_GUN * 86400)),))
            depo.rapor_ekle(con, anahtar, belge["motor"], dil, belge, firma["id"])
            depo.denetim_ekle(con, "musteri", "toplama dosyasi yuklendi, firma #%d, motor=%s, kontrol=%d" % (firma["id"], belge["motor"], len(belge["kontroller"])))
        finally:
            con.close()
        self._send(303, extra=(("Location", "/rapor/%s/" % anahtar),))

    # ---- Kip B: dogrudan baglanti (docs/kip-b-tasarim.md) ----
    def _form(self, sinir=8192):
        """urlencoded govde -> {alan: metin}. Govde gunluge yazilmaz."""
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/x-www-form-urlencoded"):
            return None
        try:
            n = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        if n < 0 or n > sinir:
            return None
        return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True).items()}

    def _baglan_baslat(self):
        f = self._form()
        if f is None:
            return self._hata(415, "tur")
        dil = f.get("dil") if f.get("dil") in ("tr", "en") else "tr"
        if not self.sinir.allow(self._ip()):
            return self._hata(429, "hiz", dil, extra=(("Retry-After", "3600"),))
        if f.get("yetki", "").strip() not in ("on", "1", "evet", "yes"):
            return self._hata(422, "yetki", dil)
        eposta = f.get("eposta", "")
        anahtar_s = depo.sirket_anahtari(eposta)
        if not anahtar_s:
            return self._hata(422, "eposta", dil)
        sirket = re.sub(r"[\x00-\x1f\x7f]", "", f.get("sirket", "")).strip()
        if not sirket or len(sirket) > 160:
            return self._hata(422, "sirket", dil)
        veritabani, kullanici = f.get("veritabani", "postgres"), f.get("kullanici", "alig_hc")
        con = depo.baglan(self.db_yolu)
        try:
            firma = depo.firma_kaydet(con, depo.firma_anahtari(eposta), sirket, eposta, "tarama")
            if firma["durum"] != "aktif":
                depo.denetim_ekle(con, "sistem", "pasif firma dogrudan baglanti istegi reddedildi, firma #%d" % firma["id"])
                return self._hata(403, "pasif", dil)
            if not firma["dogrudan_izin"]:
                depo.denetim_ekle(con, "sistem", "dogrudan baglanti izni yok, firma #%d" % firma["id"])
                return self._hata(403, "izin", dil)
            if depo.kullanim_say(con, anahtar_s) >= self.sirket_adet:
                return self._hata(429, "sinir", dil)
            if depo.istek_say(con, firma["id"]) >= depo.ISTEK_SAATLIK:
                depo.denetim_ekle(con, "sistem", "dogrudan baglanti istek siniri, firma #%d" % firma["id"])
                return self._hata(429, "deneme", dil)
            try:
                if not baglanti.AD.match(veritabani) or not baglanti.AD.match(kullanici):
                    raise hedef.Reddedildi("ad")
                h = self.hedef_dogrula(f.get("sunucu", ""), f.get("port", ""), yasak_aglar=self.yasak_aglar)
            except hedef.Reddedildi as e:
                depo.denetim_ekle(con, "sistem", "dogrudan baglanti hedefi reddedildi (%s), firma #%d" % (e.kod, firma["id"]))
                return self._hata(422, "hedef", dil)   # neden musteriye soylenmez
            anahtar, kanit = secrets.token_urlsafe(32), secrets.token_hex(16)
            depo.istek_ekle(con, anahtar, firma["id"], kanit, h.ad, h.ip, h.port, veritabani, kullanici,
                            f.get("maskele", "") in ("on", "1"), dil)
            depo.denetim_ekle(con, "musteri", "dogrudan baglanti istegi acildi, firma #%d, hedef=%s" % (firma["id"], h.ozet()[:16]))
        finally:
            con.close()
        self._send(200, hata.kanit_sayfasi(dil, anahtar, baglanti.kanit_komutu(kullanici, kanit)).encode("utf-8"), "text/html; charset=utf-8")

    def _baglan_calistir(self, token):
        f = self._form()
        con = depo.baglan(self.db_yolu)
        try:
            i = depo.istek_getir(con, token)
            if not i:
                return self._hata(404, "istek_yok")
            dil = i["dil"]
            if f is None or not f.get("parola"):
                return self._hata(422, "baglanti", dil)
            firma = depo.firma_getir(con, i["firma_id"])
            if not firma or firma["durum"] != "aktif" or not firma["dogrudan_izin"]:
                depo.istek_bitir(con, i["id"], "iptal")
                return self._hata(403, "izin", dil)
            if depo.istek_deneme(con, i["id"]) > depo.ISTEK_DENEME:
                depo.istek_bitir(con, i["id"], "deneme")
                depo.denetim_ekle(con, "sistem", "dogrudan baglanti deneme siniri, firma #%d" % firma["id"])
                return self._hata(429, "deneme", dil)
            anahtar_s = depo.sirket_anahtari(firma["eposta"])
            if depo.kullanim_say(con, anahtar_s) >= self.sirket_adet:
                return self._hata(429, "sinir", dil)
            h = hedef.Hedef(i["ad"], i["ip"], i["port"])   # ad yeniden cozulmez: dogrulanmis IP kullanilir
            if not TARAMA_YUVASI.acquire(blocking=False):
                return self._hata(503, "mesgul", dil, extra=(("Retry-After", "120"),))
            try:
                if self.calistirici_soketi:
                    belge = calistirici.uzaktan_tara(self.calistirici_soketi, h, i["veritabani"], i["kullanici"], f["parola"],
                                                     i["kanit"], maskele=bool(i["maskele"]))
                else:
                    belge = self.tara(h, i["veritabani"], i["kullanici"], f["parola"], i["kanit"], psql=self.psql,
                                      sslmode=self.sslmode, maskele=bool(i["maskele"]))
            except baglanti.BaglantiHatasi as e:
                depo.denetim_ekle(con, "sistem", "dogrudan tarama basarisiz (%s), firma #%d, hedef=%s" % (e.kod, firma["id"], h.ozet()[:16]))
                tur = {"kanit": "kanit", "super": "super", "zaman": "zaman", "mesgul": "mesgul", "calistirici": "mesgul",
                       "hedef": "hedef"}.get(e.kod, "baglanti")
                return self._hata({"zaman": 504, "mesgul": 503}.get(tur, 422), tur, dil)
            finally:
                TARAMA_YUVASI.release()
            with KILIT:
                asildi = depo.kullanim_say(con, anahtar_s) >= self.sirket_adet
                if not asildi:
                    depo.kullanim_ekle(con, anahtar_s)
            if asildi:
                return self._hata(429, "sinir", dil)
            anahtar = secrets.token_urlsafe(32)
            depo.rapor_ekle(con, anahtar, belge["motor"], dil, belge, firma["id"])
            depo.istek_bitir(con, i["id"], "tamam")
            depo.denetim_ekle(con, "musteri", "dogrudan tarama tamamlandi, firma #%d, hedef=%s, kontrol=%d" % (firma["id"], h.ozet()[:16], len(belge["kontroller"])))
        finally:
            con.close()
        self._send(303, extra=(("Location", "/rapor/%s/" % anahtar),))

    def _sil(self, token):
        con = depo.baglan(self.db_yolu)
        try:
            n = depo.rapor_sil(con, token)
            depo.denetim_ekle(con, "musteri", "rapor silindi" if n else "silme istegi: rapor yok")
        finally:
            con.close()
        self._send(303 if n else 404, extra=(("Location", "/"),) if n else ())

    def log_message(self, fmt, *a):  # yol token icerir: yazma
        yol = self.path.split("?")[0]
        if yol.startswith("/rapor/"):
            yol = "/rapor/..."
        elif yol.startswith("/api/tarama/baglan/"):
            yol = "/api/tarama/baglan/..."
        print(self.command, yol, a[1] if len(a) > 1 else "", flush=True)


def dogrudan_ayarla(ortam, H):
    """Kip B'yi yalniz ayri calistirici soketi verilmisse acar. Acildiysa True."""
    if ortam.get("ALIG_DOGRUDAN") != "1" or not ortam.get("ALIG_CALISTIRICI_SOKETI"):
        return False
    H.dogrudan = True
    H.calistirici_soketi = ortam["ALIG_CALISTIRICI_SOKETI"]
    H.yasak_aglar = tuple(x.strip() for x in ortam.get("ALIG_YASAK_AGLAR", "").split(",") if x.strip())
    return True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("ALIG_TARAMA_DB", "tarama.sqlite"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8091)
    a = ap.parse_args(argv)
    H.db_yolu = a.db
    if os.environ.get("ALIG_DOGRUDAN") == "1" and not dogrudan_ayarla(os.environ, H):
        print("UYARI: ALIG_DOGRUDAN=1 ama ALIG_CALISTIRICI_SOKETI yok; dogrudan baglanti KAPALI kaldi", flush=True)
    if os.environ.get("ALIG_MSSQL") == "1":
        H.motorlar = ("postgresql", "mssql")
    try:
        depo.denetim_anahtari()
        saklama.dogrula()
    except (depo.AnahtarHatasi, saklama.SaklamaHatasi) as ex:
        raise SystemExit("hata: %s" % ex)
    depo.baglan(a.db).close()
    print("dinliyor %s:%d" % (a.host, a.port), flush=True)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()

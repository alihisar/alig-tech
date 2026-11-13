#!/usr/bin/env python3
"""Giden e-posta. Yalnizca standart kutuphane.

Web sureci aga cikmaz: iletileri tarama.sqlite icindeki giden kutusuna (posta tablosu) yazar. Bu betik ayri bir
servis olarak (alig-posta) kutuyu bosaltir. Basariyla gonderilen iletinin metni hemen silinir: metin rapor
baglantisini, yani gizli bir kodu icerir.

  python3 tarama/posta.py --db /var/lib/alig/tarama.sqlite            # bir kez bosalt
  python3 tarama/posta.py --db /var/lib/alig/tarama.sqlite --surekli  # servis kipi

Ayarlar (ortam):
  ALIG_SMTP_SUNUCU, ALIG_SMTP_PORT (587: STARTTLS zorunlu; 465: dogrudan TLS), ALIG_SMTP_KULLANICI, ALIG_SMTP_PAROLA,
  ALIG_EPOSTA_GONDEREN (From adresi). Yerel deneme: ALIG_POSTA_DIZINI verilirse iletiler o dizine .eml olarak yazilir.
Sifresiz SMTP desteklenmez: sunucu STARTTLS sunmuyorsa gonderim hata verir, parola gonderilmez.
"""
import argparse
import os
import smtplib
import ssl
import sys
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tarama import depo  # noqa: E402

ILETI = {
    "tr": ("alig.tech sağlık taraması raporunuz",
           "Merhaba,\n\n"
           "alig.tech sağlık taramasına bu e-posta adresiyle bir toplama dosyası yüklendi. Raporu görmek için aşağıdaki "
           "bağlantıyı açın ve sayfadaki düğmeyle e-posta adresinizi doğrulayın:\n\n{baglanti}\n\n"
           "Bağlantı {saat} saat geçerlidir. Bu sürede doğrulanmayan rapor kendiliğinden silinir.\n\n"
           "Bu yüklemeyi siz yapmadıysanız bu e-postayı yok sayın. Ücretsiz tarama hakkınız kullanılmaz.\n\n"
           "alig.tech\n"),
    "en": ("Your alig.tech health check report",
           "Hello,\n\n"
           "A collection file was uploaded to the alig.tech health check with this email address. To see the report, open "
           "the link below and confirm your email address with the button on the page:\n\n{baglanti}\n\n"
           "The link is valid for {saat} hours. A report that is not confirmed in that time is deleted automatically.\n\n"
           "If you did not make this upload, ignore this email. Your free scan allowance is not used.\n\n"
           "alig.tech\n"),
}


class PostaAyarHatasi(ValueError):
    pass


def dogrulama_iletisi(dil, baglanti, saat=depo.BEKLEME_SAAT):
    """(konu, metin) dondurur."""
    konu, metin = ILETI["en" if dil == "en" else "tr"]
    return konu, metin.format(baglanti=baglanti, saat=saat)


def _ileti(gonderen, alici, konu, metin):
    m = EmailMessage()
    m["From"] = formataddr(("alig.tech", gonderen))
    m["To"] = alici
    m["Subject"] = konu
    m["Message-ID"] = make_msgid(domain=gonderen.rpartition("@")[2] or None)
    m["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    m["Auto-Submitted"] = "auto-generated"
    m.set_content(metin)
    return m


class SmtpGonderici:
    def __init__(self, sunucu, gonderen, port=587, kullanici="", parola="", zaman_asimi=20, smtp=smtplib.SMTP, smtp_ssl=smtplib.SMTP_SSL):
        self.sunucu, self.gonderen, self.port = sunucu, gonderen, int(port)
        self.kullanici, self.parola, self.zaman_asimi = kullanici, parola, zaman_asimi
        self._smtp, self._smtp_ssl = smtp, smtp_ssl

    def gonder(self, alici, konu, metin):
        baglam = ssl.create_default_context()  # sunucu sertifikasi ve adi dogrulanir
        if self.port == 465:
            s = self._smtp_ssl(self.sunucu, self.port, timeout=self.zaman_asimi, context=baglam)
        else:
            s = self._smtp(self.sunucu, self.port, timeout=self.zaman_asimi)
        try:
            if self.port != 465:
                s.ehlo()
                s.starttls(context=baglam)   # desteklenmiyorsa SMTPNotSupportedError: sifresiz gonderim yok
                s.ehlo()
            if self.kullanici:
                s.login(self.kullanici, self.parola)
            s.send_message(_ileti(self.gonderen, alici, konu, metin))
        finally:
            try:
                s.quit()
            except (smtplib.SMTPException, OSError):
                pass


class DosyaGonderici:
    """Yerel deneme: iletiyi dizine .eml olarak yazar (yalniz sahibi okur)."""

    def __init__(self, dizin, gonderen="tarama@alig.tech"):
        self.dizin, self.gonderen = Path(dizin), gonderen

    def gonder(self, alici, konu, metin):
        self.dizin.mkdir(parents=True, exist_ok=True)
        ad = self.dizin / ("%s-%d.eml" % (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"), time.monotonic_ns()))
        fd = os.open(ad, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(bytes(_ileti(self.gonderen, alici, konu, metin)))


def gonderici_kur(ortam=None):
    o = os.environ if ortam is None else ortam
    gonderen = o.get("ALIG_EPOSTA_GONDEREN", "").strip()
    if o.get("ALIG_POSTA_DIZINI"):
        return DosyaGonderici(o["ALIG_POSTA_DIZINI"], gonderen or "tarama@alig.tech")
    sunucu = o.get("ALIG_SMTP_SUNUCU", "").strip()
    if not sunucu:
        raise PostaAyarHatasi("ALIG_SMTP_SUNUCU tanimli degil")
    if "@" not in gonderen:
        raise PostaAyarHatasi("ALIG_EPOSTA_GONDEREN gecerli bir adres degil")
    port = o.get("ALIG_SMTP_PORT", "587").strip()
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise PostaAyarHatasi("ALIG_SMTP_PORT gecersiz")
    kullanici = o.get("ALIG_SMTP_KULLANICI", "").strip()
    parola = o.get("ALIG_SMTP_PAROLA", "")
    if kullanici and not parola:
        raise PostaAyarHatasi("ALIG_SMTP_KULLANICI var ama ALIG_SMTP_PAROLA yok")
    return SmtpGonderici(sunucu, gonderen, int(port), kullanici, parola)


def isle(con, gonderici, en_cok=20):
    """Giden kutusundaki bekleyen iletileri gonderir. (gonderilen, hatali) dondurur. Iletinin alicisi ve metni
    gunluge yazilmaz; yalniz kayit numarasi ve hata turu."""
    gonderilen = hatali = 0
    for pid, alici, konu, metin, _deneme in depo.posta_bekleyenler(con, en_cok):
        try:
            gonderici.gonder(alici, konu, metin)
        except (smtplib.SMTPException, OSError, ssl.SSLError) as ex:
            depo.posta_sonuc(con, pid, hata=type(ex).__name__)
            print("posta #%d gonderilemedi: %s" % (pid, type(ex).__name__), flush=True)
            hatali += 1
            continue
        depo.posta_sonuc(con, pid)
        gonderilen += 1
    return gonderilen, hatali


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("ALIG_TARAMA_DB", "tarama.sqlite"))
    ap.add_argument("--surekli", action="store_true", help="servis kipi: kutuyu aralikla bosalt")
    ap.add_argument("--aralik", type=float, default=5.0)
    a = ap.parse_args(argv)
    try:
        g = gonderici_kur()
    except PostaAyarHatasi as ex:
        print("hata: %s" % ex, file=sys.stderr)
        return 2
    while True:
        con = depo.baglan(a.db)
        try:
            isle(con, g)
        finally:
            con.close()
        if not a.surekli:
            return 0
        time.sleep(a.aralik)


if __name__ == "__main__":
    sys.exit(main())

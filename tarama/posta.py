#!/usr/bin/env python3
"""Outgoing email. Standard library only.

The web process does not reach the network: it writes messages to the outbox (the posta table) in tarama.sqlite. This script, as a separate
service (alig-posta), empties the outbox. The text of a successfully sent message is deleted immediately: the text contains the report
link, that is, a secret code.

  python3 tarama/posta.py --db /var/lib/alig/tarama.sqlite            # empty once
  python3 tarama/posta.py --db /var/lib/alig/tarama.sqlite --surekli  # service mode

Settings (environment):
  ALIG_SMTP_SUNUCU, ALIG_SMTP_PORT (587: STARTTLS mandatory; 465: direct TLS), ALIG_SMTP_KULLANICI, ALIG_SMTP_PAROLA,
  ALIG_EPOSTA_GONDEREN (From address). Local trial: if ALIG_POSTA_DIZINI is given, messages are written to that directory as .eml.
Unencrypted SMTP is not supported: if the server does not offer STARTTLS the send fails and the password is not sent.
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
from ortak import pg, pg_ayar  # noqa: E402
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


PORTAL_ILETI = {
    "tr": ("alig.tech müşteri portalı: e-posta adresinizi doğrulayın",
           "Merhaba,\n\n"
           "alig.tech müşteri portalında bu e-posta adresiyle bir hesap açma isteği yapıldı. Hesabı etkinleştirmek için aşağıdaki "
           "bağlantıyı açın ve sayfadaki düğmeyle e-posta adresinizi doğrulayın:\n\n{baglanti}\n\n"
           "Bağlantı {saat} saat geçerlidir ve yalnız bir kez kullanılabilir.\n\n"
           "Bu isteği siz yapmadıysanız bu e-postayı yok sayın. Hesap açılmaz.\n\n"
           "alig.tech\n"),
    "en": ("alig.tech customer portal: confirm your email address",
           "Hello,\n\n"
           "A request was made to open an account in the alig.tech customer portal with this email address. To activate the "
           "account, open the link below and confirm your email address with the button on the page:\n\n{baglanti}\n\n"
           "The link is valid for {saat} hours and can be used only once.\n\n"
           "If you did not make this request, ignore this email. No account is opened.\n\n"
           "alig.tech\n"),
}
PORTAL_VAR_ILETI = {
    "tr": ("alig.tech müşteri portalı: hesabınız zaten var",
           "Merhaba,\n\nBu e-posta adresiyle alig.tech müşteri portalında zaten bir hesap var. Yeni hesap açılmadı; "
           "mevcut hesabınızla giriş yapabilirsiniz:\n\n{baglanti}\n\nBu isteği siz yapmadıysanız bu e-postayı yok sayın.\n\nalig.tech\n"),
    "en": ("alig.tech customer portal: you already have an account",
           "Hello,\n\nThere is already an account in the alig.tech customer portal with this email address. No new account was "
           "opened; you can sign in with your existing account:\n\n{baglanti}\n\nIf you did not make this request, ignore this email.\n\nalig.tech\n"),
}


def portal_iletisi(dil, baglanti, saat):
    """(subject, text): account verification link."""
    konu, metin = PORTAL_ILETI["en" if dil == "en" else "tr"]
    return konu, metin.format(baglanti=baglanti, saat=saat)


def portal_var_iletisi(dil, baglanti):
    """(subject, text): an account already exists at the address; account existence is learned only from the mailbox, not from the screen."""
    konu, metin = PORTAL_VAR_ILETI["en" if dil == "en" else "tr"]
    return konu, metin.format(baglanti=baglanti)


class PostaAyarHatasi(ValueError):
    pass


def dogrulama_iletisi(dil, baglanti, saat=depo.BEKLEME_SAAT):
    """Returns (subject, text)."""
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
        baglam = ssl.create_default_context()  # the server certificate and name are verified
        if self.port == 465:
            s = self._smtp_ssl(self.sunucu, self.port, timeout=self.zaman_asimi, context=baglam)
        else:
            s = self._smtp(self.sunucu, self.port, timeout=self.zaman_asimi)
        try:
            if self.port != 465:
                s.ehlo()
                s.starttls(context=baglam)   # if unsupported, SMTPNotSupportedError: no unencrypted sending
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
    """Local trial: writes the message to the directory as .eml (readable only by the owner)."""

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
        raise PostaAyarHatasi("ALIG_SMTP_SUNUCU is not defined")
    if "@" not in gonderen:
        raise PostaAyarHatasi("ALIG_EPOSTA_GONDEREN is not a valid address")
    port = o.get("ALIG_SMTP_PORT", "587").strip()
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise PostaAyarHatasi("ALIG_SMTP_PORT is invalid")
    kullanici = o.get("ALIG_SMTP_KULLANICI", "").strip()
    parola = o.get("ALIG_SMTP_PAROLA", "")
    if kullanici and not parola:
        raise PostaAyarHatasi("ALIG_SMTP_KULLANICI is set but ALIG_SMTP_PAROLA is missing")
    return SmtpGonderici(sunucu, gonderen, int(port), kullanici, parola)


def isle(con, gonderici, en_cok=20):
    """Sends the pending messages in the outbox. Returns (sent, failed). The recipient and the text of the message are
    not written to the log; only the record number and the error type."""
    gonderilen = hatali = 0
    for pid, alici, konu, metin, _deneme in depo.posta_bekleyenler(con, en_cok):
        try:
            gonderici.gonder(alici, konu, metin)
        except (smtplib.SMTPException, OSError, ssl.SSLError) as ex:
            depo.posta_sonuc(con, pid, hata=type(ex).__name__)
            print("mail #%d could not be sent: %s" % (pid, type(ex).__name__), flush=True)
            hatali += 1
            continue
        depo.posta_sonuc(con, pid)
        gonderilen += 1
    return gonderilen, hatali


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("ALIG_TARAMA_DB", "tarama.sqlite"))
    ap.add_argument("--surekli", action="store_true", help="service mode: empty the outbox at intervals")
    ap.add_argument("--aralik", type=float, default=5.0)
    a = ap.parse_args(argv)
    try:
        g = gonderici_kur()
    except PostaAyarHatasi as ex:
        print("error: %s" % ex, file=sys.stderr)
        return 2
    global depo
    db = a.db
    try:
        pgayar = pg_ayar.yukle()
    except ValueError as ex:   # PostgreSQL configured wrongly: no silent fallback to SQLite
        print("error: %s" % ex, file=sys.stderr)
        return 2
    if pgayar is not None:   # ALIG_DB_*: the outbox lives in PostgreSQL (tarama/depo_pg.py)
        from tarama import depo_pg
        depo, db = depo_pg, pgayar
    while True:
        try:
            con = depo.baglan(db)
        except pg.PgHata as ex:
            print("error: PostgreSQL is configured but cannot be used: %s" % ex, file=sys.stderr)
            if not a.surekli:
                return 1
            time.sleep(a.aralik)
            continue
        try:
            isle(con, g)
        finally:
            con.close()
        if not a.surekli:
            return 0
        time.sleep(a.aralik)


if __name__ == "__main__":
    sys.exit(main())

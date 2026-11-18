"""Transactional outbox worker on PostgreSQL (ALIG-DB-006). Standard library only.

Guarantee, stated honestly: AT-LEAST-ONCE delivery with receiver-side dedupe, NOT exactly-once.

Enqueue (tarama/depo_pg.py posta_ekle): the intent to send is a row in alig.posta written in the SAME transaction as the business change
(upload + report + audit, portal registration + audit). If that transaction rolls back there is no message; if it commits there is exactly
one message per idempotency key (UNIQUE mesaj_anahtari, ON CONFLICT DO NOTHING). Nothing is sent inside the transaction.

Worker (this module), one attempt:
  1. claim:  a short transaction picks due rows with FOR UPDATE SKIP LOCKED and flips them to 'gonderiliyor' with a lease (kilit_utc),
             deneme = deneme + 1, then COMMITS. Concurrent workers skip each other's rows, so two workers never claim the same row.
  2. send:   AFTER the commit, outside any transaction and without holding a database lock, the sender is called. Its slow network call
             therefore never holds a row lock or a connection transaction.
  3. mark:   a second short transaction marks 'gonderildi' (text wiped: it holds the secret report link) or schedules a retry. The
             statement only matches the attempt number the worker claimed (deneme is the claim token), so a worker whose lease expired
             and whose row was re-claimed cannot overwrite the newer attempt.
Failures: a transient error schedules the next attempt with exponential backoff (GERI_CEKILME_TABAN * 2**(n-1), capped at GERI_CEKILME_TAVAN)
until POSTA_DENEME attempts, then the row is dead ('basarisiz', text wiped). A permanent refusal (all recipients refused, 5xx on DATA) goes dead
at once. A crash counts as an attempt too (deneme is incremented at claim time), so a message that kills its worker cannot loop forever.

Where a duplicate can still happen (and why it is acceptable): the process dies, or the mark transaction fails, AFTER the mail server
accepted the message and BEFORE 'gonderildi' is committed. After the lease expires the row is claimed again and the message is sent a second
time: at most once more per attempt. The same happens if a send takes longer than the lease (the worker refuses to START a send when
less than LEASE_PAYI of the lease is left, but cannot stop one in progress). Defence: every attempt of a message carries the same
idempotency key, as Message-ID '<alig-KEY@domain>' and as X-Alig-Idempotency-Key, so the receiving side can drop the repeat. Exactly-once
over SMTP is not possible without the receiver's cooperation; this module does not claim it.

Times: the database clock (clock_timestamp()) is used for backoff and leases unless a time is passed in (tests), so workers on different hosts
agree. The recipient and the text are never written to the log: only the message id and the error type.
"""
import smtplib
import time
from collections import namedtuple

from tarama import depo_pg as depo

DENEME_EN_COK = depo.POSTA_DENEME       # attempts (claims) before the dead state
GERI_CEKILME_TABAN = 30.0               # seconds before the 2nd attempt
GERI_CEKILME_TAVAN = 3600.0
KILIT_SANIYE = 300.0                    # lease: must be longer than one send (SMTP timeout 20 s) and the claimed batch
LEASE_PAYI = 60.0                       # do not start a send with less than this left of the lease
TOPLU = 10                              # messages claimed at once

Ileti = namedtuple("Ileti", "id alici konu metin deneme anahtar")
Sonuc = namedtuple("Sonuc", "gonderilen yeniden olu yitik birakilan")

_ZAMAN = "COALESCE(?::timestamptz, clock_timestamp())"


def _z(t):
    return None if t is None else t.isoformat()


def geri_cekilme(deneme, taban=GERI_CEKILME_TABAN, tavan=GERI_CEKILME_TAVAN):
    """Seconds to wait after failed attempt number `deneme` (1-based)."""
    return min(float(tavan), float(taban) * (2 ** max(0, deneme - 1)))


def kalici_hata_mi(ex):
    """A refusal that retrying cannot fix: every recipient refused, or a 5xx answer to the message data. Anything else (network, TLS,
    4xx, authentication, unknown) is treated as transient."""
    if isinstance(ex, smtplib.SMTPRecipientsRefused):
        return all(500 <= int(v[0]) < 600 for v in ex.recipients.values())
    if isinstance(ex, smtplib.SMTPDataError):
        return 500 <= int(ex.smtp_code) < 600
    return False


def talep_et(con, en_cok=TOPLU, kilit_saniye=KILIT_SANIYE, deneme_siniri=DENEME_EN_COK, simdi_=None):
    """Claim step (its own short transaction; must not be called inside another one). Returns [Ileti] for the claimed rows."""
    if con.in_transaction:
        raise RuntimeError("the outbox claim must be committed before sending: do not call it inside a transaction")
    t = _z(simdi_)
    with depo.islem(con) as c:
        # A message whose worker died on its last allowed attempt: dead, not retried again.
        c.execute("UPDATE posta SET durum='basarisiz', metin='', kilit_utc=NULL, son_hata='lease expired on the last attempt' "
                  "WHERE durum='gonderiliyor' AND kilit_utc <= " + _ZAMAN + " AND deneme >= ?", (t, deneme_siniri))
        satirlar = c.execute(
            "UPDATE posta SET durum='gonderiliyor', deneme=deneme+1, kilit_utc=" + _ZAMAN + " + make_interval(secs => ?) "
            "WHERE id IN (SELECT id FROM posta WHERE deneme < ? AND "
            "((durum='bekliyor' AND sonraki_utc <= " + _ZAMAN + ") OR (durum='gonderiliyor' AND kilit_utc <= " + _ZAMAN + ")) "
            "ORDER BY sonraki_utc, id LIMIT ? FOR UPDATE SKIP LOCKED) "
            "RETURNING id, alici, konu, metin, deneme, mesaj_anahtari",
            (t, float(kilit_saniye), deneme_siniri, t, t, int(en_cok))).fetchall()
    return sorted((Ileti(*r) for r in satirlar), key=lambda i: i.id)


def gonderildi(con, ileti, simdi_=None):
    """Mark step after a successful send. False when the claim was lost (lease expired and the row was claimed again): the message may then
    be delivered twice; the idempotency key lets the receiver drop it."""
    return con.execute("UPDATE posta SET durum='gonderildi', metin='', gonderim_utc=" + _ZAMAN + ", son_hata='', kilit_utc=NULL "
                       "WHERE id=? AND durum='gonderiliyor' AND deneme=?", (_z(simdi_), ileti.id, ileti.deneme)).rowcount == 1


def hatali(con, ileti, hata, kalici=False, deneme_siniri=DENEME_EN_COK, taban=GERI_CEKILME_TABAN, tavan=GERI_CEKILME_TAVAN, simdi_=None):
    """Mark step after a failed send. Returns 'yeniden' (retry scheduled), 'olu' (dead), or 'yitik' (claim lost, nothing changed)."""
    hata = str(hata)[:200]
    t = _z(simdi_)
    if kalici or ileti.deneme >= deneme_siniri:
        n = con.execute("UPDATE posta SET durum='basarisiz', metin='', kilit_utc=NULL, son_hata=? WHERE id=? AND durum='gonderiliyor' AND deneme=?",
                        (hata, ileti.id, ileti.deneme)).rowcount
        return "olu" if n == 1 else "yitik"
    n = con.execute("UPDATE posta SET durum='bekliyor', kilit_utc=NULL, son_hata=?, sonraki_utc=" + _ZAMAN + " + make_interval(secs => ?) "
                    "WHERE id=? AND durum='gonderiliyor' AND deneme=?",
                    (hata, t, geri_cekilme(ileti.deneme, taban, tavan), ileti.id, ileti.deneme)).rowcount
    return "yeniden" if n == 1 else "yitik"


def birak(con, ileti):
    """Give a claimed message back untouched (not sent, attempt not counted)."""
    return con.execute("UPDATE posta SET durum='bekliyor', deneme=deneme-1, kilit_utc=NULL WHERE id=? AND durum='gonderiliyor' AND deneme=?",
                       (ileti.id, ileti.deneme)).rowcount == 1


def isle(con, gonderici, en_cok=TOPLU, kilit_saniye=KILIT_SANIYE, deneme_siniri=DENEME_EN_COK, taban=GERI_CEKILME_TABAN,
         tavan=GERI_CEKILME_TAVAN, simdi_=None, saat=time.monotonic, log=print):
    """Claims due messages, sends them after the claim has committed, records the outcome. gonderici.gonder(alici, konu, metin, anahtar=...)
    must raise on failure. Returns Sonuc(gonderilen, yeniden, olu, yitik, birakilan)."""
    baslangic = saat()
    liste = talep_et(con, en_cok, kilit_saniye, deneme_siniri, simdi_)
    gonderilen = yeniden = olu = yitik = birakilan = 0
    for i in liste:
        if saat() - baslangic > max(0.0, kilit_saniye - LEASE_PAYI):   # the lease is about to run out: another worker could take the row
            birakilan += 1 if birak(con, i) else 0
            continue
        try:
            gonderici.gonder(i.alici, i.konu, i.metin, anahtar=i.anahtar)
        except Exception as ex:   # noqa: BLE001 - any sender failure is an attempt failure; the row must not stay claimed
            sonuc = hatali(con, i, type(ex).__name__, kalici_hata_mi(ex), deneme_siniri, taban, tavan, simdi_)
            log("mail #%d attempt %d failed (%s): %s" % (i.id, i.deneme, type(ex).__name__, sonuc))
            if sonuc == "yeniden":
                yeniden += 1
            elif sonuc == "olu":
                olu += 1
            else:
                yitik += 1
            continue
        if gonderildi(con, i, simdi_):
            gonderilen += 1
        else:
            yitik += 1
            log("mail #%d was sent but its claim was lost; it may be delivered twice (idempotency key %s)" % (i.id, i.anahtar))
    return Sonuc(gonderilen, yeniden, olu, yitik, birakilan)

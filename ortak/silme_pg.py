"""Company deletion + contact requests + KVKK (Turkish data protection law) deletion request in ONE PostgreSQL transaction
(ALIG-DB-003e, v5.1 section 8.3). Standard library only; uses ortak/pg.py.

In SQLite these lived in three databases (form.sqlite, yonetim.sqlite, tarama.sqlite), so yonetim/server.py had to delete the contact
requests first, then the company, and an interruption between the steps could leave half of the data. In the merged database everything
below commits together or not at all:

1. the company row is locked (FOR UPDATE: two concurrent deletions serialise; the second finds nothing and returns None);
2. its contact requests (alig.contact rows whose address maps to the company key) and their talep_durum rows (optional, `talepleri_sil`);
3. its usage records (quota), reports, portal users (codes, sessions), portal requests INCLUDING the open KVKK deletion request
   (tur = 'silme') and Mode B connection requests (the foreign keys cascade from alig.firma);
4. the company row and the firma_silinen trace (a digest, not the plain key);
5. the optional `denetim(baglanti, sonuc)` callable, run inside the same transaction, writes the audit record (the audit chain
   functions of 003c/003d plug in here): if it fails, nothing above is committed.

Returns a dict of counts, or None if the company does not exist."""
import hashlib

from tarama import depo as _tarama_depo

__all__ = ["firma_sil_birlesik"]


def _firma_ozeti(anahtar):
    return hashlib.sha256(("sirket|" + anahtar).encode()).hexdigest()    # same as tarama/depo.py _firma_ozeti


def _iz_ozeti(anahtar):
    return hashlib.sha256(("silinen|" + anahtar).encode()).hexdigest()   # same as tarama/depo.py _iz_ozeti


def _like_kacis(metin):
    return metin.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _dizi(idler):
    return "{" + ",".join(str(int(i)) for i in idler) + "}"


def firma_sil_birlesik(b, firma_id, *, talepleri_sil=True, denetim=None):
    with b.islem():
        satir = b.sorgu("SELECT anahtar FROM alig.firma WHERE id = $1 FOR UPDATE", [firma_id])
        if not satir:
            return None
        anahtar = satir[0][0]
        sonuc = {"firma": firma_id, "iletisim_talebi": 0, "rapor": 0}
        sonuc["kvkk_silme_talebi"] = b.sorgu("SELECT count(*) FROM alig.portal_talep WHERE firma_id = $1 AND tur = 'silme'", [firma_id])[0][0]
        if talepleri_sil:
            adaylar = b.sorgu("SELECT id, email FROM alig.contact WHERE lower(email) = $1 OR lower(email) LIKE $2",
                              [anahtar, "%@" + _like_kacis(anahtar)])
            idler = [i for i, e in adaylar if _tarama_depo.firma_anahtari(e or "") == anahtar]
            if idler:
                b.sorgu("DELETE FROM alig.talep_durum WHERE talep_id = ANY($1::bigint[])", [_dizi(idler)])
                b.sorgu("DELETE FROM alig.contact WHERE id = ANY($1::bigint[])", [_dizi(idler)])
            sonuc["iletisim_talebi"] = len(idler)
        b.sorgu("DELETE FROM alig.kullanim WHERE anahtar_sha256 = $1", [_firma_ozeti(anahtar)])
        b.sorgu("DELETE FROM alig.rapor WHERE firma_id = $1", [firma_id])
        sonuc["rapor"] = b.etkilenen or 0
        b.sorgu("DELETE FROM alig.firma WHERE id = $1", [firma_id])   # cascades: portal users/codes/sessions/requests, connection requests
        b.sorgu("INSERT INTO alig.firma_silinen(anahtar_sha256, silinme_utc) VALUES($1, now()) "
                "ON CONFLICT (anahtar_sha256) DO UPDATE SET silinme_utc = excluded.silinme_utc", [_iz_ozeti(anahtar)])
        if denetim is not None:
            denetim(b, sonuc)
        return sonuc

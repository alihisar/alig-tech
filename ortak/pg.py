"""PostgreSQL icin dar bir ctypes + libpq sarmalayicisi (ALIG-DB-002 DEGERLENDIRME prototipi).

Uygulamaya baglanmaz; hicbir modul bunu import etmez. Karar DB-K1 icin kanit uretir (docs/postgresql-gecis.md bolum 2).

Tasarim kurallari:
- Yalniz Python standart kutuphanesi; libpq sistemden yuklenir (Linux: libpq.so.5, Windows: libpq.dll).
- Sorgu metnine deger birlestirilmez: degerler PQexecParams ile $1, $2 olarak, metin biciminde baglanir.
- Her PGresult PQclear, her PGconn PQfinish ile kapatilir (try/finally).
- Parola hata metinlerine, repr'e ve loga yazilmaz; olasi izler maskelenir.
- Kor yeniden deneme yok: baglanti kopunca BaglantiHatasi firlatilir, islem tekrarlanmaz.

Is parcacigi guvenligi: libpq PQisthreadsafe() ile denetlenir. Bir Baglanti nesnesi ayni anda tek is parcacigi
tarafindan kullanilabilir ve is parcaciklari arasinda PAYLASILMAZ: ikinci bir is parcacigi mesgul baglantiyi
kullanmaya calisirsa EszamanliKullanimHatasi alir (bekletilmez, kuyruga alinmaz). Acik islem (islem()) yalniz
onu baslatan is parcacigina aittir. Tek istisna iptal(): baska bir is parcacigindan cagrilabilir (PQcancel).
Her is parcacigi kendi baglantisini acar.

Parametre tipi: sunucu tipi cikaramazsa ($1 tek basina SELECT icinde) hata verir; gerekirse $1::text gibi tur
doniusumu yazin. Sonuc metin biciminde gelir; yalniz bool, int, float, numeric ve timestamptz Python tipine cevrilir,
digerleri str kalir; NULL her zaman None.
"""
import ctypes
import ctypes.util
import os
import threading
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

__all__ = [
    "PgHata", "KutuphaneHatasi", "BaglantiHatasi", "SorguHatasi", "ButunlukHatasi", "BenzersizlikHatasi",
    "SorguIptalHatasi", "KilitHatasi", "SerilestirmeHatasi", "EszamanliKullanimHatasi",
    "Baglanti", "kutuphane_yukle", "thread_guvenli",
]


# --- hata siniflari -------------------------------------------------------------------------------------------

class PgHata(Exception):
    """Tum PostgreSQL katmani hatalarinin tabani."""


class KutuphaneHatasi(PgHata):
    """libpq bulunamadi ya da kullanilamaz (ornegin is parcacigi guvenli degil)."""


class BaglantiHatasi(PgHata):
    """Baglanti kurulamadi, kimlik dogrulanamadi ya da baglanti koptu. Islem tekrarlanmaz."""


class EszamanliKullanimHatasi(PgHata):
    """Baglanti baska bir is parcacigi tarafindan kullaniliyor (baglanti paylasilamaz)."""


class SorguHatasi(PgHata):
    """Sunucu sorguyu reddetti. sqlstate: 5 karakterli SQLSTATE; kisit: varsa kisit adi."""

    def __init__(self, mesaj, sqlstate=None, kisit=None):
        super().__init__(f"[{sqlstate}] {mesaj}" if sqlstate else mesaj)
        self.mesaj = mesaj
        self.sqlstate = sqlstate
        self.kisit = kisit


class ButunlukHatasi(SorguHatasi):
    """SQLSTATE sinifi 23 (butunluk kisiti)."""


class BenzersizlikHatasi(ButunlukHatasi):
    """SQLSTATE 23505."""


class SorguIptalHatasi(SorguHatasi):
    """SQLSTATE 57014: statement_timeout dolduysa ya da PQcancel ile iptal edildiyse."""


class KilitHatasi(SorguHatasi):
    """SQLSTATE 55P03: lock_timeout doldu ya da kilit alinamadi."""


class SerilestirmeHatasi(SorguHatasi):
    """SQLSTATE 40001 / 40P01: serilestirme ya da kilitlenme. Yeniden deneme karari cagirana aittir."""


def _hata_sinifi(sqlstate):
    if sqlstate == "23505":
        return BenzersizlikHatasi
    if sqlstate and sqlstate.startswith("23"):
        return ButunlukHatasi
    if sqlstate == "57014":
        return SorguIptalHatasi
    if sqlstate == "55P03":
        return KilitHatasi
    if sqlstate in ("40001", "40P01"):
        return SerilestirmeHatasi
    return SorguHatasi


# --- libpq yukleme --------------------------------------------------------------------------------------------

_yukleme_kilidi = threading.Lock()
_lib = None

CONNECTION_OK = 0
PGRES_EMPTY_QUERY, PGRES_COMMAND_OK, PGRES_TUPLES_OK = 0, 1, 2
PG_DIAG_SQLSTATE, PG_DIAG_MESSAGE_PRIMARY, PG_DIAG_CONSTRAINT_NAME = ord("C"), ord("M"), ord("n")

# OID -> doniustur (metin bicimi)
_OID_BOOL, _OID_INT8, _OID_INT2, _OID_INT4 = 16, 20, 21, 23
_OID_FLOAT4, _OID_FLOAT8, _OID_NUMERIC, _OID_TIMESTAMPTZ = 700, 701, 1700, 1184


def _aday_listesi():
    adaylar = []
    ozel = os.environ.get("ALIG_LIBPQ")
    if ozel:
        adaylar.append(ozel)
    bulunan = ctypes.util.find_library("pq")
    if bulunan:
        adaylar.append(bulunan)
    adaylar += ["libpq.so.5", "libpq.dll", "libpq.5.dylib"]
    return adaylar


def _imzalar(lib):
    vp, ci, cp = ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p
    tanim = {
        "PQconnectdb": (vp, [cp]),
        "PQstatus": (ci, [vp]),
        "PQerrorMessage": (cp, [vp]),
        "PQfinish": (None, [vp]),
        "PQexecParams": (vp, [vp, cp, ci, vp, ctypes.POINTER(cp), vp, vp, ci]),
        "PQresultStatus": (ci, [vp]),
        "PQresultErrorField": (cp, [vp, ci]),
        "PQresultErrorMessage": (cp, [vp]),
        "PQntuples": (ci, [vp]),
        "PQnfields": (ci, [vp]),
        "PQftype": (ctypes.c_uint, [vp, ci]),
        "PQgetvalue": (cp, [vp, ci, ci]),
        "PQgetisnull": (ci, [vp, ci]),
        "PQgetlength": (ci, [vp, ci, ci]),
        "PQcmdTuples": (cp, [vp]),
        "PQclear": (None, [vp]),
        "PQgetCancel": (vp, [vp]),
        "PQcancel": (ci, [vp, ctypes.c_char_p, ci]),
        "PQfreeCancel": (None, [vp]),
        "PQisthreadsafe": (ci, []),
        "PQlibVersion": (ci, []),
    }
    for ad, (donus, args) in tanim.items():
        f = getattr(lib, ad)
        f.restype = donus
        f.argtypes = args


def kutuphane_yukle(adaylar=None, onbellek=True):
    """libpq'yu yukler. Bulunamazsa ya da is parcacigi guvenli degilse KutuphaneHatasi (sessiz geri dusme yok)."""
    global _lib
    with _yukleme_kilidi:
        if onbellek and adaylar is None and _lib is not None:
            return _lib
        denenen, son_hata = [], None
        for aday in (adaylar if adaylar is not None else _aday_listesi()):
            denenen.append(aday)
            try:
                lib = ctypes.CDLL(aday)
                _imzalar(lib)
            except (OSError, AttributeError) as e:
                son_hata = e
                continue
            if lib.PQisthreadsafe() != 1:
                raise KutuphaneHatasi(f"libpq is parcacigi guvenli degil ({aday}); kullanilmaz")
            if onbellek and adaylar is None:
                _lib = lib
            return lib
        raise KutuphaneHatasi(
            "libpq bulunamadi (denenen: " + ", ".join(denenen) + "). Linux: 'libpq5' paketini kurun; "
            "Windows: libpq.dll ve bagimliliklarini PATH'e koyun ya da ALIG_LIBPQ ile yol verin. "
            f"Son hata: {son_hata}")


def thread_guvenli():
    return kutuphane_yukle().PQisthreadsafe() == 1


# --- yardimcilar ----------------------------------------------------------------------------------------------

def _maskele(metin, sirlar):
    """Metindeki bilinen sirlari ***'a cevirir."""
    for s in sirlar:
        if s:
            metin = metin.replace(s, "***")
    return metin


def _kontrol_nul(deger, ad):
    if "\x00" in deger:
        raise ValueError(f"{ad}: NUL karakteri olamaz")


def _baglanti_dizgisi(ayarlar):
    """anahtar='deger' dizgisi; degerde \\ ve ' kacislanir. None degerler atlanir."""
    parcalar = []
    for anahtar, deger in ayarlar.items():
        if deger is None:
            continue
        deger = str(deger)
        _kontrol_nul(deger, anahtar)
        kacisli = deger.replace("\\", "\\\\").replace("'", "\\'")
        parcalar.append(f"{anahtar}='{kacisli}'")
    return " ".join(parcalar)


def _parametre_metni(deger):
    """Python degerini metin bicimli parametreye (bytes) cevirir; None -> NULL."""
    if deger is None:
        return None
    if isinstance(deger, bool):
        return b"true" if deger else b"false"
    if isinstance(deger, (int, float, Decimal)):
        return str(deger).encode("ascii")
    if isinstance(deger, datetime):
        if deger.tzinfo is None or deger.utcoffset() is None:
            raise ValueError("saat dilimsiz datetime reddedildi (timestamptz icin UTC ya da ofsetli verin)")
        return deger.isoformat().encode("ascii")
    if isinstance(deger, date):
        return deger.isoformat().encode("ascii")
    if isinstance(deger, (bytes, bytearray)):
        return b"\\x" + bytes(deger).hex().encode("ascii")
    if isinstance(deger, str):
        _kontrol_nul(deger, "parametre")
        return deger.encode("utf-8")
    raise TypeError(f"desteklenmeyen parametre tipi: {type(deger).__name__}")


def _doniustur(oid, metin):
    if oid == _OID_BOOL:
        return metin == "t"
    if oid in (_OID_INT2, _OID_INT4, _OID_INT8):
        return int(metin)
    if oid in (_OID_FLOAT4, _OID_FLOAT8):
        return float(metin)
    if oid == _OID_NUMERIC:
        return Decimal(metin)
    if oid == _OID_TIMESTAMPTZ:
        try:
            return datetime.fromisoformat(metin)
        except ValueError:  # infinity gibi ozel degerler
            return metin
    return metin


# --- baglanti -------------------------------------------------------------------------------------------------

class Baglanti:
    """Tek bir PGconn. Is parcacigi arasinda paylasilmaz (modul belgesine bakin). Dogrudan degil, baglan() ile olusturun."""

    def __init__(self):
        raise TypeError("Baglanti.baglan(...) kullanin")

    @classmethod
    def baglan(cls, *, host=None, port=None, dbname=None, user=None, password=None,
               baglanti_zaman_asimi=10, statement_timeout_ms=30000, lock_timeout_ms=5000,
               bosta_islem_zaman_asimi_ms=60000, uygulama_adi="alig", sslmode=None):
        """Baglanir ve oturum zaman asimlarini ayarlar. Yeniden deneme yoktur; basarisizlikta BaglantiHatasi."""
        lib = kutuphane_yukle()
        dizgi = _baglanti_dizgisi({
            "host": host, "port": port, "dbname": dbname, "user": user, "password": password,
            "connect_timeout": int(baglanti_zaman_asimi), "application_name": uygulama_adi,
            "client_encoding": "UTF8", "sslmode": sslmode,
        })
        self = object.__new__(cls)
        self._lib = lib
        self._sirlar = [password]
        self._conn = None
        self._iptal = None
        self._kopuk = False
        self._islemde = False
        self._islem_sahibi = None
        self._mesgul = threading.Lock()      # sorgu sirasinda tutulur; paylasimi reddetmek icin
        self._iptal_kilidi = threading.Lock()  # iptal() ile kapat() arasi
        conn = lib.PQconnectdb(dizgi.encode("utf-8"))
        del dizgi
        if not conn:
            raise BaglantiHatasi("baglanti nesnesi olusturulamadi (bellek)")
        if lib.PQstatus(conn) != CONNECTION_OK:
            mesaj = self._metin(lib.PQerrorMessage(conn))
            lib.PQfinish(conn)
            raise BaglantiHatasi(_maskele(mesaj or "baglanti kurulamadi", self._sirlar))
        self._conn = conn
        try:
            self._iptal = lib.PQgetCancel(conn)  # iptal() baska is parcaciginden guvenle kullanilsin diye simdi alinir
            for ad, deger in (("statement_timeout", statement_timeout_ms), ("lock_timeout", lock_timeout_ms),
                              ("idle_in_transaction_session_timeout", bosta_islem_zaman_asimi_ms),
                              ("TimeZone", "UTC")):
                self.sorgu("SELECT set_config($1, $2, false)", [ad, str(deger)])
        except BaseException:
            self.kapat()
            raise
        return self

    # -- yardimcilar
    @staticmethod
    def _metin(b):
        return b.decode("utf-8", "replace").strip() if b else ""

    def __repr__(self):
        durum = "kapali" if self._conn is None else ("kopuk" if self._kopuk else "acik")
        return f"<pg.Baglanti {durum}>"

    __str__ = __repr__

    @property
    def islemde(self):
        return self._islemde

    @property
    def kopuk(self):
        return self._kopuk

    # -- sorgu
    def sorgu(self, sql, parametreler=()):
        """Tek SQL ifadesi; $1, $2 ... ile parametre. Satir listesi (tuple) doner; komutlarda bos liste."""
        if self._islemde and self._islem_sahibi != threading.get_ident():
            raise EszamanliKullanimHatasi("islem baska bir is parcacigina ait")
        if not self._mesgul.acquire(blocking=False):
            raise EszamanliKullanimHatasi("baglanti baska bir is parcacigi tarafindan kullaniliyor; paylasilamaz")
        try:
            return self._calistir(sql, parametreler)
        finally:
            self._mesgul.release()

    def _calistir(self, sql, parametreler):
        if self._conn is None:
            raise BaglantiHatasi("baglanti kapali")
        if self._kopuk:
            raise BaglantiHatasi("baglanti kopmus; yeni baglanti acin")
        lib = self._lib
        _kontrol_nul(sql, "sql")
        degerler = [_parametre_metni(p) for p in parametreler]
        n = len(degerler)
        dizi = (ctypes.c_char_p * n)(*degerler) if n else None
        res = lib.PQexecParams(self._conn, sql.encode("utf-8"), n, None, dizi, None, None, 0)
        if not res:
            return self._bos_sonuc_hatasi()
        try:
            durum = lib.PQresultStatus(res)
            if durum in (PGRES_COMMAND_OK, PGRES_TUPLES_OK, PGRES_EMPTY_QUERY):
                return self._satirlar(res, durum)
            sqlstate = self._metin(lib.PQresultErrorField(res, PG_DIAG_SQLSTATE)) or None
            birincil = self._metin(lib.PQresultErrorField(res, PG_DIAG_MESSAGE_PRIMARY)) \
                or self._metin(lib.PQresultErrorMessage(res))
            kisit = self._metin(lib.PQresultErrorField(res, PG_DIAG_CONSTRAINT_NAME)) or None
        finally:
            lib.PQclear(res)
        # SQLSTATE'siz hata istemci tarafi hatasidir (baglanti kaybi dahil); 08xxx ve 57P01-03 baglanti/sunucu kapanmasi
        if (lib.PQstatus(self._conn) != CONNECTION_OK or not sqlstate or sqlstate.startswith("08")
                or sqlstate in ("57P01", "57P02", "57P03")):
            self._kopuk = True
            raise BaglantiHatasi(_maskele(f"baglanti koptu: {birincil}", self._sirlar))
        # ayrinti (DETAIL) bilerek eklenmez: satir degerleri icerebilir
        raise _hata_sinifi(sqlstate)(_maskele(birincil, self._sirlar), sqlstate, kisit)

    def _bos_sonuc_hatasi(self):
        self._kopuk = self._kopuk or self._lib.PQstatus(self._conn) != CONNECTION_OK
        mesaj = self._metin(self._lib.PQerrorMessage(self._conn)) or "sonuc alinamadi"
        raise BaglantiHatasi(_maskele(mesaj, self._sirlar))

    def _satirlar(self, res, durum):
        lib = self._lib
        self.etkilenen = None
        sayi = self._metin(lib.PQcmdTuples(res))
        if sayi.isdigit():
            self.etkilenen = int(sayi)
        if durum != PGRES_TUPLES_OK:
            return []
        satir_sayisi, kolon_sayisi = lib.PQntuples(res), lib.PQnfields(res)
        tipler = [lib.PQftype(res, j) for j in range(kolon_sayisi)]
        sonuc = []
        for i in range(satir_sayisi):
            satir = []
            for j in range(kolon_sayisi):
                if lib.PQgetisnull(res, i, j):
                    satir.append(None)
                else:
                    ham = ctypes.string_at(lib.PQgetvalue(res, i, j), lib.PQgetlength(res, i, j))
                    satir.append(_doniustur(tipler[j], ham.decode("utf-8")))
            sonuc.append(tuple(satir))
        return sonuc

    # -- islem
    @contextmanager
    def islem(self):
        """with baglanti.islem(): BEGIN; cikista COMMIT; istisnada ROLLBACK ve istisna yeniden firlatilir."""
        if self._islemde:
            raise PgHata("ic ice islem desteklenmez")
        self.sorgu("BEGIN")
        self._islemde = True
        self._islem_sahibi = threading.get_ident()
        try:
            yield self
        except BaseException:
            self._geri_al()
            raise
        try:
            self._calistir_islem_sonu("COMMIT")
        except BaseException:
            self._geri_al()
            raise
        finally:
            self._islemde = False
            self._islem_sahibi = None

    def _calistir_islem_sonu(self, komut):
        if not self._mesgul.acquire(blocking=False):
            raise EszamanliKullanimHatasi("baglanti baska bir is parcacigi tarafindan kullaniliyor")
        try:
            self._calistir(komut, ())
        finally:
            self._mesgul.release()

    def _geri_al(self):
        try:
            if self._conn is not None and not self._kopuk:
                self._calistir_islem_sonu("ROLLBACK")
        except PgHata:
            pass  # asil hata zaten yayilir; baglanti gerekirse kopuk isaretlenmistir
        finally:
            self._islemde = False
            self._islem_sahibi = None

    # -- iptal ve kapatma
    def iptal(self):
        """Calisan sorguyu PQcancel ile iptal eder; baska is parcaciginden cagrilabilir. Sorgu SorguIptalHatasi alir."""
        with self._iptal_kilidi:
            if self._iptal is None:
                raise BaglantiHatasi("baglanti kapali")
            tampon = ctypes.create_string_buffer(256)
            if self._lib.PQcancel(self._iptal, tampon, 256) != 1:
                raise PgHata("iptal istegi gonderilemedi: " + _maskele(self._metin(tampon.value), self._sirlar))

    def kapat(self):
        """PQfinish; birden cok kez cagrilabilir. Baska is parcacigi sorgu calistiriyorsa reddeder."""
        if not self._mesgul.acquire(blocking=False):
            raise EszamanliKullanimHatasi("baglanti kullanimda; kapatilamaz")
        try:
            with self._iptal_kilidi:
                if self._iptal is not None:
                    self._lib.PQfreeCancel(self._iptal)
                    self._iptal = None
                if self._conn is not None:
                    self._lib.PQfinish(self._conn)
                    self._conn = None
        finally:
            self._mesgul.release()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.kapat()

    def __del__(self):
        try:
            if getattr(self, "_conn", None) is not None:
                self.kapat()
        except Exception:
            pass

"""Ortak kanit modeli. PostgreSQL ve SQL Server kurallari ayni kayit bicimini uretir; rapor, panel ve ileride saglik
puani ile gecmis karsilastirmasi bu kayitlari okur. Dil modeli yok: ayni belge her zaman ayni kayitlari verir.

Her kural her taramada tek bir kayit uretir (KAYIT_ALANLARI):
  kural        kalici kimlik, ornegin PG-SEC-001. Kimlik degismez; kaldirilan kuralin kimligi yeniden kullanilmaz.
  motor        postgresql | mssql
  kategori     KATEGORILER
  durum        FAIL, WARNING, UNKNOWN, UNAVAILABLE, NOT_APPLICABLE, PASS
  onem         bulgu varsa en yuksek onem (kritik ... bilgi), yoksa None
  guven        HIGH, MEDIUM, LOW. Kanit yoksa (UNKNOWN, UNAVAILABLE) None
  kaynak       okunan katalog gorunumleri, islevler ya da ayarlar
  kontroller   kaniti saglayan toplama denetimleri (katalog kimlikleri; belge ust alani icin "toplayici")
  toplama_utc  verinin toplandigi an (belgedeki olusturma_utc)
  neden        UNKNOWN, UNAVAILABLE ve NOT_APPLICABLE icin neden kodu (metinleri tarama/rapor.py)
  gozlem       kuralin okudugu ayar ve sayilar. Nesne adi icermez
  bulgular     kuralin urettigi bulgular (tarama/kurallar.py bicimi, kural alanlariyla)
  ad, beklenen kuralin adi ve gecme kosulu (tr, en)

Durum kurallari:
  - Bulgu varsa FAIL (kritik, yuksek) ya da WARNING (orta, dusuk, bilgi); kapsam kismi olsa bile: bulunan sorun gercektir.
  - Birincil kaynak gelmediyse UNAVAILABLE: calistirilmadi, yetki, zaman asimi, surumde yok, yedek sunucu, hata, sinir.
  - Veri geldi ama sonuca yetmiyorsa UNKNOWN: bicim ya da tur gecersiz, zorunlu deger eksik, beklenen satir yok,
    bazi veritabanlari taranmadi, ek kaynak gelmedi.
  - Veri, kuralin konusunun sunucuda olmadigini gosteriyorsa NOT_APPLICABLE (ornegin replikasyon slotu yok).
  - Ancak butun kaynaklar eksiksiz geldiyse ve bulgu yoksa PASS. Veri yokken PASS cikmaz.
"""
from datetime import datetime, timezone
from typing import NamedTuple

from tarama.yukleme import TUR_DENETIMI

DURUMLAR = ("FAIL", "WARNING", "UNKNOWN", "UNAVAILABLE", "NOT_APPLICABLE", "PASS")
KANITSIZ = ("UNKNOWN", "UNAVAILABLE")
GUVENLER = ("HIGH", "MEDIUM", "LOW")
KATEGORILER = ("guvenlik", "performans", "konfigurasyon", "bakim", "kapasite", "ha_dr", "yedek")
KATEGORI_KISALTMA = {"guvenlik": "SEC", "performans": "PERF", "konfigurasyon": "CONFIG", "bakim": "MAINT",
                     "kapasite": "CAP", "ha_dr": "HA", "yedek": "BACKUP"}
SATIR = ("tek", "en_az_bir", "herhangi")
ONEM_SIRASI = ("kritik", "yuksek", "orta", "dusuk", "bilgi")
BULGU_DURUMU = {"kritik": "FAIL", "yuksek": "FAIL", "orta": "WARNING", "dusuk": "WARNING", "bilgi": "WARNING"}
# Toplayicinin yazdigi hata nedenleri: veri hic gelmedi.
ERISILEMEZ = frozenset({"calistirilmadi", "yetki", "zaman_asimi", "desteklenmiyor", "yedek_sunucu", "hata", "sinir", "ad"})
# SQL Server on surumdur: sorgular gercek sunucuda sinanmadi, kanit guveni en cok MEDIUM.
GUVEN_TAVANI = {"mssql": "MEDIUM"}
TOPLAYICI = "toplayici"   # kaynak olarak belgenin ust alani (superuser): toplayicinin baglandigi hesap
KAYIT_ALANLARI = ("kural", "motor", "kategori", "durum", "onem", "guven", "kaynak", "kontroller", "toplama_utc",
                  "neden", "gozlem", "bulgular", "ad", "beklenen")

# Kural icinde tur ya da anahtar hatasi: kural "gecersiz_veri" ile UNKNOWN olur, rapor ve panel dusmez.
_VERI_HATASI = (TypeError, KeyError, ValueError, ZeroDivisionError, OverflowError, AttributeError, IndexError)


class Belirsiz(Exception):
    """Veri geldi ama kural sonuca varamiyor: durum UNKNOWN."""

    def __init__(self, neden="eksik_veri"):
        super().__init__(neden)
        self.neden = neden


class Uygulanmaz(Exception):
    """Veri, kuralin konusunun bu sunucuda olmadigini gosteriyor: durum NOT_APPLICABLE."""

    def __init__(self, neden):
        super().__init__(neden)
        self.neden = neden


class Kaynak(NamedTuple):
    kontrol: str
    satir: str = "herhangi"   # tek: tam bir satir; en_az_bir: bos sonuc veri yok demektir; herhangi: bos sonuc gecerli
    zorunlu: tuple = ()        # satirda dolu olmasi gereken kolonlar; bos olan satir degerlendirmeye girmez, sonuc kismi olur
    ek: bool = False           # ek kaynak: gelmezse kural yine calisir (bulgu raporlanir) ama PASS veremez


class Kural(NamedTuple):
    kimlik: str
    motor: str
    kategori: str
    guven: str                 # HIGH: ayar ya da katalog durumu; MEDIUM: istatistik ya da anlik goruntu; LOW: dolayli isaret
    kaynaklar: tuple           # ilki birincil kaynak
    ad: dict
    beklenen: dict             # gecme kosulu (tr, en)
    fn: object                 # fn(birincil_satirlar, girdi) -> bulgu listesi; Belirsiz ya da Uygulanmaz firlatabilir
    kaynak: tuple = ()         # bos ise kaynak denetimlerinin katalogdaki "kaynak" listesi


def kayitci(liste, motor):
    """Kural fonksiyonunu kaydeden dekorator: @kural("PG-SEC-001", "guvenlik", "HIGH", [Kaynak(...)], ad, beklenen)."""
    def kural(kimlik, kategori, guven, kaynaklar, ad, beklenen, kaynak=()):
        def sar(fn):
            liste.append(Kural(kimlik, motor, kategori, guven, tuple(kaynaklar), ad, beklenen, fn, tuple(kaynak)))
            return fn
        return sar
    return kural


class Girdi:
    """Kural fonksiyonunun gordugu veri. Satirlar zorunlu kolonlari dolu ve turu dogru olanlardir."""

    def __init__(self, belge, taranan, veri):
        self.belge, self.taranan, self._veri = belge, taranan, veri
        self.kismi_nedenler, self.gozlem = [], {}

    def satirlar(self, kontrol):
        """Kaynagin satirlari; ek kaynak gelmediyse None."""
        return self._veri.get(kontrol)

    def kismi(self, neden):
        """Sonuc tam degil: bulgu yoksa durum UNKNOWN olur."""
        self.kismi_nedenler.append(neden)

    def gozle(self, degerler=None, **kv):
        """PASS durumunda da raporda gosterilen olcum. Yalniz ayar ve sayi; nesne adi yazilmaz."""
        self.gozlem.update(degerler or {}, **kv)


def _parse_utc(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _tam_kapsam(kontroller):
    """Sunucudaki baglanilabilir her veritabani tarandi mi (pg_kapsam)? Bilinmiyorsa False."""
    e = kontroller.get("pg_kapsam")
    if not isinstance(e, dict) or e.get("durum") != "ok" or e.get("atlanan"):
        return False
    r = e.get("satirlar")
    if not isinstance(r, list) or not r or not all(isinstance(x, dict) for x in r):
        return False
    toplamlar = {x.get("veritabani_sayisi") for x in r}
    if len(toplamlar) != 1:
        return False
    toplam = toplamlar.pop()
    return isinstance(toplam, int) and not isinstance(toplam, bool) and toplam == len({x.get("veritabani") for x in r})


def _satir_sorunu(s, zorunlu, turler):
    for kolon in zorunlu:
        if s.get(kolon) is None:
            return "eksik_veri"
    for kolon, tur in turler.items():
        v = s.get(kolon)
        if v is not None and not TUR_DENETIMI[tur](v):
            return "gecersiz_veri"
    return None


def _oku(belge, kontroller, kaynak, katalog_by_id, turler, tam_kapsam):
    """(satirlar, durum, neden, kismi_nedenler). satirlar None ise kaynak yok ya da kullanilamaz."""
    if kaynak.kontrol == TOPLAYICI:
        v = belge.get("superuser")
        if not isinstance(v, bool):
            return None, "UNAVAILABLE", "calistirilmadi", []
        return [{"superuser": v}], None, None, []
    e = kontroller.get(kaynak.kontrol)
    if e is None:
        return None, "UNAVAILABLE", "calistirilmadi", []
    if not isinstance(e, dict) or e.get("durum") not in ("ok", "hata"):
        return None, "UNKNOWN", "gecersiz_veri", []
    if e["durum"] == "hata":
        neden = e.get("neden")
        return None, "UNAVAILABLE", neden if neden in ERISILEMEZ else "hata", []
    satirlar = e.get("satirlar")
    if not isinstance(satirlar, list) or not all(isinstance(s, dict) for s in satirlar):
        return None, "UNKNOWN", "gecersiz_veri", []
    kismi = []
    if katalog_by_id.get(kaynak.kontrol, {}).get("kapsam") == "veritabani" and (e.get("atlanan") or not tam_kapsam):
        kismi.append("kismi_veritabani")
    tur = turler.get(kaynak.kontrol, {})
    tam = []
    for s in satirlar:
        sorun = _satir_sorunu(s, kaynak.zorunlu, tur)
        if sorun is None:
            tam.append(s)
        elif sorun not in kismi:
            kismi.append(sorun)
    if kaynak.satir == "tek" and len(satirlar) > 1:
        return None, "UNKNOWN", "gecersiz_veri", []
    if kaynak.satir != "herhangi" and not tam:
        return None, "UNKNOWN", next((k for k in kismi if k != "kismi_veritabani"), "eksik_veri"), []
    return tam, None, None, kismi


def _kayit(kural, belge, kontroller, taranan, katalog_by_id, turler, tam_kapsam):
    kaynak = list(kural.kaynak) or sorted({ad for k in kural.kaynaklar for ad in katalog_by_id.get(k.kontrol, {}).get("kaynak", ())})
    tavan = GUVEN_TAVANI.get(kural.motor)
    guven = max(kural.guven, tavan, key=GUVENLER.index) if tavan else kural.guven   # daha dusuk olani
    kayit = {"kural": kural.kimlik, "motor": kural.motor, "kategori": kural.kategori, "durum": None, "onem": None, "guven": None,
             "kaynak": kaynak, "kontroller": [k.kontrol for k in kural.kaynaklar], "toplama_utc": belge.get("olusturma_utc"),
             "neden": None, "gozlem": {}, "bulgular": [], "ad": dict(kural.ad), "beklenen": dict(kural.beklenen)}   # kopya: kayit degisse de kural degismez

    def bitir(durum, neden=None):
        kayit["durum"], kayit["neden"] = durum, neden
        kayit["guven"] = None if durum in KANITSIZ else guven
        return kayit

    veri, kismi = {}, []
    for k in kural.kaynaklar:
        satirlar, durum, neden, k_kismi = _oku(belge, kontroller, k, katalog_by_id, turler, tam_kapsam)
        if satirlar is None:
            if not k.ek:
                return bitir(durum, neden)
            kismi.append(neden)
        veri[k.kontrol] = satirlar
        kismi += k_kismi
    g = Girdi(belge, taranan, veri)
    uygulanmaz = None
    try:
        bulgular = list(kural.fn(veri[kural.kaynaklar[0].kontrol], g) or [])
    except Uygulanmaz as u:
        bulgular, uygulanmaz = [], u.neden
    except Belirsiz as b:
        kayit["gozlem"] = g.gozlem
        return bitir("UNKNOWN", b.neden)
    except _VERI_HATASI:
        return bitir("UNKNOWN", "gecersiz_veri")
    kayit["gozlem"] = g.gozlem
    kismi += g.kismi_nedenler
    if bulgular:
        for b in bulgular:
            b.update(kural=kural.kimlik, kategori=kural.kategori, durum=BULGU_DURUMU[b["onem"]], guven=guven, kaynak=kaynak)
        kayit["bulgular"] = bulgular
        kayit["onem"] = min((b["onem"] for b in bulgular), key=ONEM_SIRASI.index)
        return bitir("FAIL" if any(b["durum"] == "FAIL" for b in bulgular) else "WARNING")
    if kismi:
        return bitir("UNKNOWN", kismi[0])
    if uygulanmaz:
        return bitir("NOT_APPLICABLE", uygulanmaz)
    return bitir("PASS")


class Sonuc:
    """Bir belgenin degerlendirmesi: kayitlar (kural sirasiyla), bulgular (onem sirasiyla), olculemeyenler."""

    def __init__(self, kayitlar):
        self.kayitlar = kayitlar
        self.bulgular = sorted((b for k in kayitlar for b in k["bulgular"]), key=lambda b: ONEM_SIRASI.index(b["onem"]))
        self.olculemeyen = [(k["kural"], k["neden"]) for k in kayitlar if k["durum"] in KANITSIZ]

    def sayim(self):
        return {d: sum(1 for k in self.kayitlar if k["durum"] == d) for d in DURUMLAR}


def calistir(belge, kurallar, katalog_by_id, turler):
    """Belgedeki veriyi kurallardan gecirir; her kural icin bir kayit. Bozuk belge de kayit uretir (UNAVAILABLE)."""
    belge = belge if isinstance(belge, dict) else {}
    kontroller = belge.get("kontroller") if isinstance(belge.get("kontroller"), dict) else {}
    taranan = _parse_utc(belge.get("olusturma_utc")) or datetime.now(timezone.utc)
    tam = _tam_kapsam(kontroller)
    return Sonuc([_kayit(k, belge, kontroller, taranan, katalog_by_id, turler, tam) for k in kurallar])

"""Veri siniflari ve saklama politikasi (tek yer). Yalnizca standart kutuphane.

Sureler ortamdan ayarlanir: ALIG_SAKLAMA_<SINIF>_GUN. "0" ya da "suresiz" suresiz demektir
(yalniz suresiz secilebilen siniflarda). Varsayilanlar hukuken onaylanmis degerler DEGILDIR;
onay bekler: docs/doldurulacak.md.
"""
import os

# ad: (varsayilan gun ya da None=suresiz, suresiz secilebilir mi, nerede uygulanir, aciklama)
SINIFLAR = {
    "rapor": (30, False, "tarama.sqlite", "Tarama raporu ve bulgulari; bitis tarihi olusturulurken yazilir"),
    "baglanti_istegi": (1, False, "tarama.sqlite", "Dogrudan baglanti istegi (parola yok); suresi dolunca silinir"),
    "firma": (365, True, "tarama.sqlite", "Firma kaydi (ad, e-posta); son etkinlikten sonra, etkin raporu yoksa silinir"),
    "talep": (365, True, "form.sqlite, yonetim.sqlite", "Iletisim talebi ve durum notu; olusturulmasindan sonra silinir"),
    "posta": (7, False, "tarama.sqlite", "Giden e-posta kaydi (alici, konu); metin gonderilince hemen silinir"),
    "denetim": (None, True, "tum zincirler", "Denetim zinciri; silme zinciri bozar, bu yuzden suresiz tutulur ve disa aktarilan zincir basi ile korunur"),
}
SABIT = {
    "sinir_penceresi": "30 gun (depo.SINIR_GUN): kod sabiti, is kurali; sayim kayitlari bu sureden sonra silinir",
    "oturum": "yonetim paneli oturumu: kullanim suresine gore dolar, parola degisince silinir (yonetim/depo.py)",
    "portal": "musteri portali: hesap (e-posta, parola ozeti) firma silinince silinir; dogrulama kodu 24 saat, oturum bostayken 30 dk ve en cok 8 saat, giris denemesi 1 gun (tarama/portal_depo.py)",
}


class SaklamaHatasi(ValueError):
    pass


def ortam_adi(sinif):
    return "ALIG_SAKLAMA_%s_GUN" % sinif.upper()


def gun(sinif, ortam=None):
    """Sinifin saklama suresi (gun) ya da None (suresiz). Gecersiz deger acik hata verir, sessizce varsayilana donmez."""
    varsayilan, suresiz_olur, _, _ = SINIFLAR[sinif]
    ham = (os.environ if ortam is None else ortam).get(ortam_adi(sinif), "").strip().lower()
    if not ham:
        return varsayilan
    if ham in ("0", "suresiz"):
        if not suresiz_olur:
            raise SaklamaHatasi("%s suresiz olamaz" % ortam_adi(sinif))
        return None
    if not ham.isdigit() or not 1 <= int(ham) <= 3650:
        raise SaklamaHatasi("%s 1-3650 arasi gun sayisi olmali" % ortam_adi(sinif))
    return int(ham)


def tablo(ortam=None):
    """[(sinif, sure_metni, nerede, aciklama, varsayilan_mi)] panel ve belge icin."""
    satirlar = []
    for ad, (varsayilan, _, yer, aciklama) in SINIFLAR.items():
        g = gun(ad, ortam)
        satirlar.append((ad, "suresiz" if g is None else "%d gün" % g, yer, aciklama, g == varsayilan))
    return satirlar


def dogrula(ortam=None):
    """Tum siniflari dener; ilk gecersiz degerde SaklamaHatasi."""
    for ad in SINIFLAR:
        gun(ad, ortam)

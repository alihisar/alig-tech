"""Musteri portali sayfalari ve yollari (/portal/). Yalnizca standart kutuphane. Varsayilan KAPALI: ALIG_PORTAL=1.

Yollar:
  GET  /portal/                   giris sayfasi; oturum varsa firmanin raporlari
  GET  /portal/kayit              hesap isteme formu        POST /portal/kayit
  POST /portal/giris              POST /portal/cikis
  GET  /portal/dogrula/<kod>      e-postadaki baglanti: GET hicbir sey degistirmez, hesap dugmeyle (POST) etkinlesir
  GET  /portal/rapor/<id>/        firmanin raporu (?gorunum=yonetici|teknik)
Firma izolasyonu tarama/portal_depo.py'dedir: bu dosya firma kimligi bilmez, yalniz Kapsam kullanir.
"""
import re
from html import escape
from urllib.parse import parse_qs, urlparse

from tarama import depo, kurallar, portal_depo, posta, puan, rapor

KOD = re.compile(r"^/portal/dogrula/([A-Za-z0-9_\-]{43})$")
RAPOR = re.compile(r"^/portal/rapor/([0-9]{1,12})/?$")
RAPOR_SIL = re.compile(r"^/portal/rapor/([0-9]{1,12})/sil$")
COREZ = "alig_portal"
CSP = "default-src 'self'; img-src 'self'; style-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"

M = {
    "tr": {"baslik": "Müşteri portalı", "giris": "Giriş yap", "eposta": "E-posta", "parola": "Parola", "sirket": "Firma adı",
           "parola_n": "En az %d karakter.", "kayit": "Hesap iste", "kayit_l": "Hesabınız yok mu?", "giris_l": "Hesabınız var mı?",
           "kayit_a": "Kurumsal e-posta adresinizle bir hesap isteyin. Adresinize bir doğrulama bağlantısı göndeririz; hesap, bağlantı onaylanınca açılır. Aynı kurumsal alan adındaki kullanıcılar aynı firmanın raporlarını görür.",
           "hatali": "E-posta ya da parola hatalı.", "engelli": "Çok fazla deneme yapıldı. %d dakika sonra tekrar deneyin.",
           "pasif": "Hesabınız askıya alınmış. Bizimle iletişime geçin.",
           "gonderildi": "İstek alındı", "gonderildi_l": "Bu adrese bir doğrulama e-postası gönderdik (bağlantı %d saat geçerli ve tek kullanımlıktır). Gelmediyse istenmemiş klasörüne bakın ya da birkaç dakika sonra yeniden deneyin.",
           "dogrula": "E-posta adresinizi doğrulayın", "dogrula_l": "Hesabı etkinleştirmek için düğmeye basın.", "dogrula_d": "Hesabı etkinleştir",
           "dogrulandi": "Hesabınız etkinleştirildi", "dogrulandi_l": "Şimdi giriş yapabilirsiniz.",
           "dogrula_yok": "Bağlantı geçersiz", "dogrula_yok_l": "Bu bağlantı geçersiz, süresi dolmuş ya da daha önce kullanılmış. Hesap isteğini yenileyin.",
           "e_eposta": "Geçerli bir e-posta adresi girin.", "e_parola": "Parola %d ile %d karakter arasında olmalı.", "e_sirket": "Firma adını girin (en çok 160 karakter).",
           "e_istek": "İstek işlenemedi.", "e_hiz": "Çok fazla istek. Bir süre sonra tekrar deneyin.", "e_kaynak": "İstek reddedildi.",
           "firma": "Firma", "cikis": "Çıkış yap", "raporlar": "Raporlarınız", "rapor_yok": "Henüz raporunuz yok.",
           "rapor_b": ("Rapor", "Tarama zamanı (UTC)", "Motor", "Bulgular", "Sağlık puanı"), "rapor_g": "Raporu aç", "geri": "Raporlara dön",
           "puan_yok": "-", "bulgu_yok": "bulgu yok", "bulgu_n": "%d bulgu", "bulunamadi": "Bulunamadı", "bulunamadi_l": "Böyle bir rapor yok.",
           "nav": ("Raporlar", "Taleplerim", "Hesap ve veri"), "degisim": "Önceki taramaya göre", "degisim_yok": "-",
           "degisim_puan": "puan %s", "kullanim": "Ücretsiz tarama hakkınız", "kullanim_d": "%d / %d kullanıldı (son %d gün), kalan: %d",
           "kullanim_y": "En eski hakkınız %s tarihinde (UTC) yenilenir.", "sil": "Sil",
           "sil_b": "Raporu sil", "sil_l": "Bu raporu kalıcı olarak silmek istiyor musunuz? Silinen rapor geri getirilemez ve ücretsiz tarama hakkınızı geri vermez.",
           "sil_d": "Raporu kalıcı olarak sil", "silindi": "Rapor silindi", "silindi_l": "Rapor kalıcı olarak silindi.", "vazgec": "Vazgeç",
           "talepler": "Taleplerim", "talep_yeni": "Yeni hizmet talebi", "talep_yok": "Henüz talebiniz yok.",
           "talep_a": "Denetim ya da destek isteyin; talebinizi ekibimiz inceler ve e-postanızla size döner. Talep bir hizmet sözleşmesi ya da fiyat teklifi yerine geçmez.",
           "tur": "Talep türü", "turler": {"denetim": "Veritabanı denetimi", "destek": "DBA desteği", "diger": "Diğer"},
           "konu": "Konu", "mesaj": "Mesaj", "talep_g": "Talebi gönder", "talep_tamam": "Talebiniz alındı",
           "talep_tamam_l": "Talebiniz kaydedildi. Ekibimiz inceleyip size dönecek.",
           "talep_b": ("Zaman (UTC)", "Tür", "Konu", "Durum"),
           "durumlar": {"yeni": "Alındı", "inceleniyor": "İnceleniyor", "tamamlandi": "Tamamlandı", "reddedildi": "Reddedildi"},
           "e_tur": "Geçerli bir talep türü seçin.", "e_konu": "Konuyu girin (en çok 120 karakter).", "e_mesaj": "Mesajı girin (en çok 2000 karakter).",
           "e_sinir": "Bir günde en çok 5 talep gönderebilirsiniz. Yarın tekrar deneyin.", "e_csrf": "Form kodu geçersiz. Sayfayı yenileyip tekrar deneyin.",
           "hesap": "Hesap ve veri", "hesap_a": "Hesabınızın ve firmanıza ait raporların silinmesini isteyebilirsiniz. Talep kaydedilir; kimliğinizi doğrulayıp silme işlemini ekibimiz yapar. Silinen veri geri getirilemez. Denetim kaydı (kim, ne zaman, hangi işlem) bütünlüğü için tutulur; içinde parola, rapor içeriği ya da e-posta adresi bulunmaz.",
           "hesap_d": "Hesap ve verilerimin silinmesini iste", "hesap_var": "Silme talebiniz alındı (durum: %s). Ekibimiz sizinle iletişime geçecek.",
           "hesap_yeni": "Silme talebiniz alındı", "hesap_yeni_l": "Talebiniz kaydedildi. Ekibimiz kimliğinizi doğrulayıp silme işlemini yapacak.",
           "hesap_firma": "Firma", "hesap_eposta": "Giriş e-postası",
           "ana": "alig.tech"},
    "en": {"baslik": "Customer portal", "giris": "Sign in", "eposta": "Email", "parola": "Password", "sirket": "Company name",
           "parola_n": "At least %d characters.", "kayit": "Request an account", "kayit_l": "No account yet?", "giris_l": "Already have an account?",
           "kayit_a": "Request an account with your company email address. We send a confirmation link to that address; the account opens once the link is confirmed. Users with the same company domain see the same company's reports.",
           "hatali": "Wrong email or password.", "engelli": "Too many attempts. Try again in %d minutes.",
           "pasif": "Your account is suspended. Please contact us.",
           "gonderildi": "Request received", "gonderildi_l": "We sent a confirmation email to this address (the link is valid for %d hours and can be used once). If it does not arrive, check your spam folder or try again in a few minutes.",
           "dogrula": "Confirm your email address", "dogrula_l": "Press the button to activate the account.", "dogrula_d": "Activate account",
           "dogrulandi": "Your account is active", "dogrulandi_l": "You can sign in now.",
           "dogrula_yok": "Invalid link", "dogrula_yok_l": "This link is invalid, expired or already used. Request the account again.",
           "e_eposta": "Enter a valid email address.", "e_parola": "The password must be between %d and %d characters.", "e_sirket": "Enter the company name (at most 160 characters).",
           "e_istek": "The request could not be processed.", "e_hiz": "Too many requests. Try again later.", "e_kaynak": "Request rejected.",
           "firma": "Company", "cikis": "Sign out", "raporlar": "Your reports", "rapor_yok": "You have no reports yet.",
           "rapor_b": ("Report", "Scan time (UTC)", "Engine", "Findings", "Health score"), "rapor_g": "Open report", "geri": "Back to reports",
           "puan_yok": "-", "bulgu_yok": "no findings", "bulgu_n": "%d findings", "bulunamadi": "Not found", "bulunamadi_l": "There is no such report.",
           "nav": ("Reports", "My requests", "Account and data"), "degisim": "Compared with the previous scan", "degisim_yok": "-",
           "degisim_puan": "score %s", "kullanim": "Your free scan allowance", "kullanim_d": "%d of %d used (last %d days), remaining: %d",
           "kullanim_y": "Your oldest allowance renews on %s (UTC).", "sil": "Delete",
           "sil_b": "Delete report", "sil_l": "Do you want to delete this report permanently? A deleted report cannot be restored and does not give back your free scan allowance.",
           "sil_d": "Delete the report permanently", "silindi": "Report deleted", "silindi_l": "The report was deleted permanently.", "vazgec": "Cancel",
           "talepler": "My requests", "talep_yeni": "New service request", "talep_yok": "You have no requests yet.",
           "talep_a": "Ask for an audit or support; our team reviews your request and replies by email. A request is not a service contract or a price quote.",
           "tur": "Request type", "turler": {"denetim": "Database audit", "destek": "DBA support", "diger": "Other"},
           "konu": "Subject", "mesaj": "Message", "talep_g": "Send request", "talep_tamam": "Request received",
           "talep_tamam_l": "Your request was saved. Our team will review it and get back to you.",
           "talep_b": ("Time (UTC)", "Type", "Subject", "Status"),
           "durumlar": {"yeni": "Received", "inceleniyor": "In review", "tamamlandi": "Completed", "reddedildi": "Rejected"},
           "e_tur": "Choose a valid request type.", "e_konu": "Enter the subject (at most 120 characters).", "e_mesaj": "Enter the message (at most 2000 characters).",
           "e_sinir": "You can send at most 5 requests a day. Try again tomorrow.", "e_csrf": "The form code is invalid. Reload the page and try again.",
           "hesap": "Account and data", "hesap_a": "You can ask for your account and your company's reports to be deleted. The request is recorded; our team verifies your identity and carries out the deletion. Deleted data cannot be restored. The audit log (who, when, which action) is kept for integrity; it contains no password, report content or email address.",
           "hesap_d": "Request deletion of my account and data", "hesap_var": "Your deletion request was received (status: %s). Our team will contact you.",
           "hesap_yeni": "Deletion request received", "hesap_yeni_l": "Your request was saved. Our team will verify your identity and carry out the deletion.",
           "hesap_firma": "Company", "hesap_eposta": "Sign-in email",
           "ana": "alig.tech"},
}


def _dil(deger):
    return deger if deger in M else "tr"


def _kabuk(d, baslik, icerik, kapsam=None):
    m = M[d]
    kok = "/en/" if d == "en" else "/"
    nav = ""
    if kapsam is not None:
        baglar = "".join("<a href=\"%s\">%s</a>" % (h_, escape(a)) for h_, a in zip(("/portal/", "/portal/talepler", "/portal/hesap"), m["nav"]))
        nav = ("<div class=\"portal-nav\"><nav aria-label=\"%s\">%s</nav><form method=\"post\" action=\"/portal/cikis\"><input type=\"hidden\" name=\"csrf\" value=\"%s\">"
               "<span>%s: %s</span> <button class=\"btn btn-ghost\" type=\"submit\">%s</button></form></div>") % (
            escape(m["baslik"]), baglar, escape(kapsam.csrf), escape(m["firma"]), escape(kapsam.firma_ad), escape(m["cikis"]))
    return ("<!doctype html>\n<html lang=\"%s\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex,nofollow\"><title>%s | alig.tech</title>"
            "<link rel=\"stylesheet\" href=\"/assets/base.css\"><link rel=\"stylesheet\" href=\"/assets/style.css\"></head><body>"
            "<header class=\"top\"><div class=\"wrap\"><a class=\"brand\" href=\"%s\"><img src=\"/assets/logo.svg\" width=\"176\" height=\"36\" alt=\"alig.tech\"></a></div></header>"
            "<main id=\"main\"><div class=\"wrap\">%s</div>%s</main></body></html>\n") % (d, escape(baslik), kok, nav, icerik)


def _alan(ad, etiket, tur="text", ek="", not_=""):
    return ("<div class=\"field field-wide\"><label for=\"p-%s\">%s</label><input id=\"p-%s\" name=\"%s\" type=\"%s\" required %s>%s</div>"
            % (ad, escape(etiket), ad, ad, tur, ek, "<p class=\"fine\">%s</p>" % escape(not_) if not_ else ""))


def giris_sayfasi(d, hata_metni=""):
    m = M[d]
    icerik = ("<article class=\"prose portal-page\"><h1>%s</h1>%s<form class=\"form\" method=\"post\" action=\"/portal/giris\">"
              "<input type=\"hidden\" name=\"dil\" value=\"%s\">%s%s<p class=\"form-foot\"><button class=\"btn\" type=\"submit\">%s</button></p></form>"
              "<p class=\"fine\">%s <a href=\"/portal/kayit?dil=%s\">%s</a></p></article>") % (
        escape(m["giris"]), "<p class=\"err\" role=\"alert\">%s</p>" % escape(hata_metni) if hata_metni else "", d,
        _alan("eposta", m["eposta"], "email", "maxlength=\"200\" autocomplete=\"username\""),
        _alan("parola", m["parola"], "password", "maxlength=\"%d\" autocomplete=\"current-password\"" % portal_depo.PAROLA_EN_COK),
        escape(m["giris"]), escape(m["kayit_l"]), d, escape(m["kayit"]))
    return _kabuk(d, m["giris"], icerik)


def kayit_sayfasi(d, hata_metni=""):
    m = M[d]
    icerik = ("<article class=\"prose portal-page\"><h1>%s</h1><p class=\"lead\">%s</p>%s<form class=\"form\" method=\"post\" action=\"/portal/kayit\">"
              "<input type=\"hidden\" name=\"dil\" value=\"%s\">%s%s%s<p class=\"form-foot\"><button class=\"btn\" type=\"submit\">%s</button></p></form>"
              "<p class=\"fine\">%s <a href=\"/portal/?dil=%s\">%s</a></p></article>") % (
        escape(m["kayit"]), escape(m["kayit_a"]), "<p class=\"err\" role=\"alert\">%s</p>" % escape(hata_metni) if hata_metni else "", d,
        _alan("sirket", m["sirket"], ek="maxlength=\"160\" autocomplete=\"organization\""),
        _alan("eposta", m["eposta"], "email", "maxlength=\"200\" autocomplete=\"email\""),
        _alan("parola", m["parola"], "password", "minlength=\"%d\" maxlength=\"%d\" autocomplete=\"new-password\"" % (portal_depo.PAROLA_EN_AZ, portal_depo.PAROLA_EN_COK),
              m["parola_n"] % portal_depo.PAROLA_EN_AZ),
        escape(m["kayit"]), escape(m["giris_l"]), d, escape(m["giris"]))
    return _kabuk(d, m["kayit"], icerik)


def mesaj_sayfasi(d, baslik, metin, baglanti=None):
    m = M[d]
    ek = "<p><a class=\"btn\" href=\"%s\">%s</a></p>" % (baglanti[0], escape(baglanti[1])) if baglanti else ""
    return _kabuk(d, baslik, "<article class=\"prose portal-page\"><h1>%s</h1><p class=\"lead\">%s</p>%s</article>" % (escape(baslik), escape(metin), ek))


def dogrula_sayfasi(d, kod):
    m = M[d]
    return _kabuk(d, m["dogrula"], ("<article class=\"prose portal-page\"><h1>%s</h1><p class=\"lead\">%s</p>"
                                    "<form method=\"post\" action=\"/portal/dogrula/%s\"><input type=\"hidden\" name=\"dil\" value=\"%s\">"
                                    "<p><button class=\"btn\" type=\"submit\">%s</button></p></form></article>") % (
        escape(m["dogrula"]), escape(m["dogrula_l"]), escape(kod), d, escape(m["dogrula_d"])))


def _bulgu_puan(belge):
    """(bulgu_sayisi, puan_metni). Bozuk rapor listeyi dusurmez."""
    try:
        s = kurallar.incele(belge)
        pn = puan.hesapla(s)
        return len(s.bulgular), None if pn.genel is None else "%d/100" % pn.genel
    except Exception:  # noqa: BLE001 - tek bozuk rapor tum listeyi bozmasin
        return None, None


def _degisim(ks, r, m):
    """Onceki taramaya gore puan degisimi (ayni firma ve sunucu kimligi); yoksa '-'. Bozuk rapor listeyi dusurmez."""
    try:
        o = ks.onceki(r)
        if not o:
            return m["degisim_yok"]
        a, y = puan.hesapla(kurallar.incele(o["belge"])).genel, puan.hesapla(kurallar.incele(r["belge"])).genel
        if a is None or y is None:
            return m["degisim_yok"]
        f = y - a
        return m["degisim_puan"] % ("+%d" % f if f > 0 else ("\u2212%d" % -f if f < 0 else "0"))
    except Exception:  # noqa: BLE001
        return m["degisim_yok"]


DEGISIM_SATIR = 20   # karsilastirma her satirda onceki raporu okur: yalniz en yeni satirlar icin hesaplanir


def panel_sayfasi(ks, sirket_adet):
    m = M[ks.dil]
    satir = []
    for i, r in enumerate(ks.raporlar()):
        n, p = _bulgu_puan(r["belge"])
        bulgu = "-" if n is None else (m["bulgu_yok"] if n == 0 else m["bulgu_n"] % n)
        degisim = _degisim(ks, r, m) if i < DEGISIM_SATIR else m["degisim_yok"]
        zaman = r["belge"].get("olusturma_utc", "-") if isinstance(r["belge"], dict) else "-"
        satir.append("<tr><th scope=\"row\">#%d</th><td data-label=\"%s\">%s</td><td data-label=\"%s\">%s</td><td data-label=\"%s\">%s</td>"
                     "<td data-label=\"%s\">%s</td><td data-label=\"%s\">%s</td><td><a href=\"/portal/rapor/%d/\">%s</a> <a href=\"/portal/rapor/%d/sil\">%s</a></td></tr>" % (
                         r["id"], escape(m["rapor_b"][1]), escape(str(zaman)), escape(m["rapor_b"][2]), escape(str(r["motor"])), escape(m["rapor_b"][3]), escape(bulgu),
                         escape(m["rapor_b"][4]), escape(p or m["puan_yok"]), escape(m["degisim"]), escape(degisim), r["id"], escape(m["rapor_g"]), r["id"], escape(m["sil"])))
    tablo = ("<table class=\"tiers durumlar\"><thead><tr>%s<th scope=\"col\">%s</th><th scope=\"col\"></th></tr></thead><tbody>%s</tbody></table>" % (
        "".join("<th scope=\"col\">%s</th>" % escape(b) for b in m["rapor_b"]), escape(m["degisim"]), "".join(satir))) if satir else "<p>%s</p>" % escape(m["rapor_yok"])
    k = ks.kullanim(sirket_adet)
    kul = "<p>%s</p>" % escape(m["kullanim_d"] % (k["kullanilan"], k["sinir"], k["gun"], k["kalan"]))
    if k["yenilenme_utc"]:
        kul += "<p class=\"fine\">%s</p>" % escape(m["kullanim_y"] % k["yenilenme_utc"])
    return _kabuk(ks.dil, m["baslik"], "<article class=\"prose portal-page\"><h1>%s</h1><h2>%s</h2>%s<h2>%s</h2>%s</article>" % (
        escape(m["baslik"]), escape(m["kullanim"]), kul, escape(m["raporlar"]), tablo), ks)


def sil_sayfasi(ks, rid):
    m = M[ks.dil]
    return _kabuk(ks.dil, m["sil_b"], ("<article class=\"prose portal-page\"><h1>%s</h1><p class=\"lead\">%s</p>"
                                       "<form method=\"post\" action=\"/portal/rapor/%d/sil\"><input type=\"hidden\" name=\"csrf\" value=\"%s\">"
                                       "<p><button class=\"btn\" type=\"submit\">%s</button> <a class=\"btn btn-ghost\" href=\"/portal/\">%s</a></p></form></article>") % (
        escape(m["sil_b"]), escape(m["sil_l"]), rid, escape(ks.csrf), escape(m["sil_d"]), escape(m["vazgec"])), ks)


def talepler_sayfasi(ks, hata_metni="", form=None):
    m = M[ks.dil]
    form = form or {}
    satir = ["<tr><td data-label=\"%s\">%s</td><td data-label=\"%s\">%s</td><td data-label=\"%s\">%s</td><td data-label=\"%s\">%s</td></tr>" % (
        escape(m["talep_b"][0]), escape(t["olusturma_utc"]), escape(m["talep_b"][1]), escape(m["turler"].get(t["tur"], t["tur"])),
        escape(m["talep_b"][2]), escape(t["konu"]), escape(m["talep_b"][3]), escape(m["durumlar"][t["durum"]]))
        for t in ks.talepler() if t["tur"] != "silme"]
    liste = ("<table class=\"tiers durumlar\"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
        "".join("<th scope=\"col\">%s</th>" % escape(b) for b in m["talep_b"]), "".join(satir))) if satir else "<p>%s</p>" % escape(m["talep_yok"])
    secenek = "".join("<option value=\"%s\"%s>%s</option>" % (k, " selected" if form.get("tur") == k else "", escape(v)) for k, v in m["turler"].items())
    f = ("<form class=\"form\" method=\"post\" action=\"/portal/talepler\"><input type=\"hidden\" name=\"csrf\" value=\"%s\">"
         "<div class=\"field field-wide\"><label for=\"t-tur\">%s</label><select id=\"t-tur\" name=\"tur\">%s</select></div>"
         "<div class=\"field field-wide\"><label for=\"t-konu\">%s</label><input id=\"t-konu\" name=\"konu\" type=\"text\" maxlength=\"%d\" value=\"%s\" required></div>"
         "<div class=\"field field-wide\"><label for=\"t-mesaj\">%s</label><textarea id=\"t-mesaj\" name=\"mesaj\" rows=\"6\" maxlength=\"%d\" required>%s</textarea></div>"
         "<p class=\"form-foot\"><button class=\"btn\" type=\"submit\">%s</button></p></form>") % (
        escape(ks.csrf), escape(m["tur"]), secenek, escape(m["konu"]), portal_depo.KONU_EN_COK, escape(form.get("konu", "")),
        escape(m["mesaj"]), portal_depo.MESAJ_EN_COK, escape(form.get("mesaj", "")), escape(m["talep_g"]))
    return _kabuk(ks.dil, m["talepler"], "<article class=\"prose portal-page\"><h1>%s</h1><p>%s</p>%s<h2>%s</h2>%s<h2>%s</h2>%s</article>" % (
        escape(m["talepler"]), escape(m["talep_a"]), "<p class=\"err\" role=\"alert\">%s</p>" % escape(hata_metni) if hata_metni else "",
        escape(m["talep_yeni"]), f, escape(m["talepler"]), liste), ks)


def hesap_sayfasi(ks):
    m = M[ks.dil]
    acik = [t for t in ks.talepler() if t["tur"] == "silme" and t["durum"] in ("yeni", "inceleniyor")]
    if acik:
        islem = "<p class=\"lead\">%s</p>" % escape(m["hesap_var"] % m["durumlar"][acik[0]["durum"]])
    else:
        islem = ("<form method=\"post\" action=\"/portal/hesap/silme-talebi\"><input type=\"hidden\" name=\"csrf\" value=\"%s\">"
                 "<p><button class=\"btn\" type=\"submit\">%s</button></p></form>") % (escape(ks.csrf), escape(m["hesap_d"]))
    return _kabuk(ks.dil, m["hesap"], ("<article class=\"prose portal-page\"><h1>%s</h1><dl class=\"facts\"><dt>%s</dt><dd>%s</dd><dt>%s</dt><dd>%s</dd></dl>"
                                       "<p>%s</p>%s</article>") % (escape(m["hesap"]), escape(m["hesap_firma"]), escape(ks.firma_ad),
                                                                   escape(m["hesap_eposta"]), escape(ks.eposta), escape(m["hesap_a"]), islem), ks)


# ---- istek isleme ----

def _cerez(h):
    for parca in (h.headers.get("Cookie") or "").split(";"):
        ad, _, deger = parca.strip().partition("=")
        if ad == COREZ:
            return deger
    return ""


def _ayni_kaynak(h):
    """Durum degistiren isteklerde Origin (yoksa Referer) bu sitenin Host'u olmali. Eksikse reddedilir."""
    kaynak = h.headers.get("Origin") or h.headers.get("Referer") or ""
    host = h.headers.get("Host") or ""
    try:
        return bool(host) and urlparse(kaynak).netloc == host
    except ValueError:
        return False


def _gonder(h, kod, sayfa, extra=()):
    h._send(kod, sayfa.encode("utf-8"), "text/html; charset=utf-8",
            extra=(("Content-Security-Policy", CSP), ("X-Frame-Options", "DENY")) + tuple(extra))


def _yonlendir(h, yer, extra=()):
    h._send(303, extra=(("Location", yer),) + tuple(extra))


def _cerez_yaz(h, kod, sure):
    return ("Set-Cookie", "%s=%s; Path=/portal; HttpOnly; SameSite=Strict; Max-Age=%d%s" % (COREZ, kod, sure, "; Secure" if h.portal_cerez_guvenli else ""))


def isle(h, metod):
    u = urlparse(h.path)
    yol, q = u.path, parse_qs(u.query)
    if not h.portal:
        return h._send(404, b"yok\n")
    if yol == "/portal":
        return h._send(301, extra=(("Location", "/portal/"),))
    d = _dil((q.get("dil") or ["tr"])[0])
    con = depo.baglan(h.db_yolu)
    try:
        if metod == "GET":
            return _get(h, con, yol, q, d)
        return _post(h, con, yol, d)
    finally:
        con.close()


def _bulunamadi(ks):
    m = M[ks.dil]
    return _kabuk(ks.dil, m["bulunamadi"], "<article class=\"prose portal-page\"><h1>%s</h1><p>%s</p><p><a href=\"/portal/\">%s</a></p></article>" % (
        escape(m["bulunamadi"]), escape(m["bulunamadi_l"]), escape(m["geri"])), ks)


def _get(h, con, yol, q, d):
    ks = portal_depo.kapsam(con, _cerez(h))
    if yol == "/portal/":
        return _gonder(h, 200, panel_sayfasi(ks, h.sirket_adet) if ks else giris_sayfasi(d))
    if yol == "/portal/kayit":
        return _gonder(h, 200, kayit_sayfasi(d))
    mk = KOD.match(yol)
    if mk:
        dil = portal_depo.kod_bekleyen(con, mk.group(1))
        m = M[d]
        if not dil:
            return _gonder(h, 404, mesaj_sayfasi(d, m["dogrula_yok"], m["dogrula_yok_l"], ("/portal/kayit?dil=%s" % d, m["kayit"])))
        return _gonder(h, 200, dogrula_sayfasi(dil, mk.group(1)))
    if yol in ("/portal/talepler", "/portal/hesap") or RAPOR_SIL.match(yol):
        if not ks:
            return _yonlendir(h, "/portal/")
        if yol == "/portal/talepler":
            return _gonder(h, 200, talepler_sayfasi(ks))
        if yol == "/portal/hesap":
            return _gonder(h, 200, hesap_sayfasi(ks))
        rid = int(RAPOR_SIL.match(yol).group(1))
        if not ks.rapor(rid):   # baska firmanin ya da olmayan rapor icin onay sayfasi bile gosterilmez
            return _gonder(h, 404, _bulunamadi(ks))
        return _gonder(h, 200, sil_sayfasi(ks, rid))
    mr = RAPOR.match(yol)
    if mr:
        if not ks:
            return _yonlendir(h, "/portal/")
        r = ks.rapor(int(mr.group(1)))
        m = M[ks.dil]
        if not r:
            return _gonder(h, 404, _bulunamadi(ks))
        onceki = ks.onceki(r)
        g = rapor.gorunum_sec((q.get("gorunum") or [None])[0])
        govde, _, _ = rapor.govde(r, ks.dil, "", eylemler=False, onceki=onceki, gorunum=g)
        depo.denetim_ekle(con, "portal:%d" % ks.kullanici_id, "portal raporu goruntulendi #%d" % r["id"],
                          {"firma": ks.firma_id, "rapor": r["id"], "kullanici": ks.kullanici_id, "sonuc": "basarili"})
        return _gonder(h, 200, _kabuk(ks.dil, rapor.M[ks.dil]["baslik"], "<p><a href=\"/portal/\">%s</a> <a href=\"/portal/rapor/%d/sil\">%s</a></p>%s" % (escape(m["geri"]), r["id"], escape(m["sil"]), govde), ks))
    return h._send(404, b"yok\n")


def _post(h, con, yol, d):
    f = h._form(32768)
    m0 = M[d]
    if f is None:
        return _gonder(h, 415, mesaj_sayfasi(d, m0["baslik"], m0["e_istek"]))
    d = _dil(f.get("dil"))
    m = M[d]
    if not _ayni_kaynak(h):
        return _gonder(h, 403, mesaj_sayfasi(d, m["baslik"], m["e_kaynak"]))
    if yol == "/portal/cikis":
        ks = portal_depo.kapsam(con, _cerez(h))
        if ks and portal_depo.csrf_dogru(ks, f.get("csrf")):
            depo.denetim_ekle(con, "portal:%d" % ks.kullanici_id, "portal cikisi yapildi", {"firma": ks.firma_id, "kullanici": ks.kullanici_id, "sonuc": "basarili"})
            portal_depo.cikis(con, _cerez(h))
        return _yonlendir(h, "/portal/", (_cerez_yaz(h, "", 0),))
    ks = portal_depo.kapsam(con, _cerez(h)) if yol in ("/portal/talepler", "/portal/hesap/silme-talebi") or RAPOR_SIL.match(yol) else None
    if ks is not None or yol in ("/portal/talepler", "/portal/hesap/silme-talebi") or RAPOR_SIL.match(yol):
        return _oturumlu_post(h, con, yol, f, ks)
    if yol == "/portal/giris":
        if not h.sinir.allow(h._ip()):
            return _gonder(h, 429, mesaj_sayfasi(d, m["baslik"], m["e_hiz"]), (("Retry-After", "900"),))
        kod, neden = portal_depo.giris(con, f.get("eposta", ""), f.get("parola", ""), h._ip())
        if kod:
            return _yonlendir(h, "/portal/", (_cerez_yaz(h, kod, portal_depo.OTURUM_EN_COK_SAAT * 3600),))
        if neden == "engelli":
            return _gonder(h, 429, giris_sayfasi(d, m["engelli"] % portal_depo.DENEME_PENCERE_DK), (("Retry-After", str(portal_depo.DENEME_PENCERE_DK * 60)),))
        return _gonder(h, 403 if neden == "pasif" else 401, giris_sayfasi(d, m["pasif"] if neden == "pasif" else m["hatali"]))
    if yol == "/portal/kayit":
        return _kayit(h, con, f, d)
    mk = KOD.match(yol)
    if mk:
        durum, _, _ = portal_depo.dogrula(con, mk.group(1))
        if durum == "tamam":
            return _gonder(h, 200, mesaj_sayfasi(d, m["dogrulandi"], m["dogrulandi_l"], ("/portal/?dil=%s" % d, m["giris"])))
        if durum == "pasif":
            return _gonder(h, 403, mesaj_sayfasi(d, m["baslik"], m["pasif"]))
        return _gonder(h, 404, mesaj_sayfasi(d, m["dogrula_yok"], m["dogrula_yok_l"], ("/portal/kayit?dil=%s" % d, m["kayit"])))
    return h._send(404, b"yok\n")


def _kayit(h, con, f, d):
    m = M[d]
    if not h.sinir.allow(h._ip()):
        return _gonder(h, 429, mesaj_sayfasi(d, m["baslik"], m["e_hiz"]), (("Retry-After", "3600"),))
    eposta = f.get("eposta", "")
    eposta_n = eposta.strip().lower() if isinstance(eposta, str) else ""
    try:
        with depo.islem(con) as c:
            # Ayni adrese 24 saatte en cok posta_adres_siniri ileti: asilirsa yanit yine ayni (hesap varligi ve sinir sizmaz)
            sinir_asildi = depo.firma_anahtari(eposta_n) is not None and depo.posta_say(c, eposta_n) >= h.posta_adres_siniri
            if sinir_asildi:
                depo.denetim_ekle(c, "sistem", "portal kaydi: posta siniri", {"sonuc": "reddedildi", "neden": "posta"})
            else:
                durum, kod = portal_depo.kayit(c, eposta, f.get("parola", ""), f.get("sirket", ""), d)
                if durum == "yeni":
                    konu, metin = posta.portal_iletisi(d, "%s/portal/dogrula/%s" % (h.site_adresi, kod), portal_depo.KOD_SAAT)
                else:
                    konu, metin = posta.portal_var_iletisi(d, "%s/portal/" % h.site_adresi)
                depo.posta_ekle(c, eposta_n, konu, metin)
                depo.denetim_ekle(c, "musteri", "portal hesap istegi alindi", {"sonuc": "bekliyor" if durum == "yeni" else "reddedildi", "neden": None if durum == "yeni" else "var"})
    except portal_depo.PortalHata as e:
        metin = {"eposta": m["e_eposta"], "parola": m["e_parola"] % (portal_depo.PAROLA_EN_AZ, portal_depo.PAROLA_EN_COK), "sirket": m["e_sirket"]}[e.kod]
        return _gonder(h, 422, kayit_sayfasi(d, metin))
    return _gonder(h, 200, mesaj_sayfasi(d, m["gonderildi"], m["gonderildi_l"] % portal_depo.KOD_SAAT))


def _oturumlu_post(h, con, yol, f, ks):
    """Oturum ve form kodu (csrf) gerektiren islemler. Oturum yoksa giris sayfasina, kod yanlissa 403."""
    if ks is None:
        return _yonlendir(h, "/portal/")
    m = M[ks.dil]
    if not portal_depo.csrf_dogru(ks, f.get("csrf")):
        return _gonder(h, 403, mesaj_sayfasi(ks.dil, m["baslik"], m["e_csrf"]))
    ms = RAPOR_SIL.match(yol)
    if ms:
        if not ks.rapor_sil(int(ms.group(1))):
            return _gonder(h, 404, _bulunamadi(ks))
        return _gonder(h, 200, _kabuk(ks.dil, m["silindi"], "<article class=\"prose portal-page\"><h1>%s</h1><p class=\"lead\">%s</p><p><a class=\"btn\" href=\"/portal/\">%s</a></p></article>" % (
            escape(m["silindi"]), escape(m["silindi_l"]), escape(m["geri"])), ks))
    if yol == "/portal/hesap/silme-talebi":
        _, yeni = ks.silme_talebi_ekle()
        return _gonder(h, 200, _kabuk(ks.dil, m["hesap_yeni"], "<article class=\"prose portal-page\"><h1>%s</h1><p class=\"lead\">%s</p><p><a href=\"/portal/hesap\">%s</a></p></article>" % (
            escape(m["hesap_yeni"] if yeni else m["hesap"]), escape(m["hesap_yeni_l"]), escape(m["hesap"])), ks))
    if not h.sinir.allow(h._ip()):
        return _gonder(h, 429, mesaj_sayfasi(ks.dil, m["baslik"], m["e_hiz"]), (("Retry-After", "3600"),))
    tid, neden = ks.talep_ekle(f.get("tur"), f.get("konu"), f.get("mesaj"))
    if tid is None:
        return _gonder(h, 429 if neden == "sinir" else 422, talepler_sayfasi(ks, m["e_" + neden], f))
    return _gonder(h, 200, _kabuk(ks.dil, m["talep_tamam"], "<article class=\"prose portal-page\"><h1>%s</h1><p class=\"lead\">%s</p><p><a href=\"/portal/talepler\">%s</a></p></article>" % (
        escape(m["talep_tamam"]), escape(m["talep_tamam_l"]), escape(m["talepler"])), ks))

"""Yukleme hatalari icin musteriye gosterilen sayfa. Tum degerler html.escape ile yazilir."""
from html import escape

M = {
    "tr": {
        "ust": "Sağlık taraması", "ne": "Ne yapmalı", "teknik": "Teknik ayrıntı",
        "geri": "Tarama sayfasına dön", "kilavuz": "Hazırlık kılavuzunu aç", "iletisim": "Bize yazın",
        "yetki": ("Yetki beyanı eksik", "Dosyayı yüklemek için \"Bu veritabanını taratmaya yetkiliyim\" kutusunu işaretlemeniz gerekir.",
                  "Tarama sayfasına dönüp kutuyu işaretleyin ve dosyayı yeniden yükleyin."),
        "eposta": ("E-posta adresi geçersiz", "Yazdığınız e-posta adresi tanınmadı.",
                   "Kurumsal e-posta adresinizi ad@sirket.com biçiminde yazıp yeniden deneyin."),
        "sirket": ("Şirket adı eksik", "Şirket adı boş bırakılmış ya da 160 karakterden uzun.",
                   "Şirketinizin adını yazıp dosyayı yeniden yükleyin."),
        "json": ("Dosya okunamadı", "Yüklediğiniz dosya geçerli bir toplama dosyası değil.",
                 "Betiğin yazdığı alig-toplama.json dosyasını değiştirmeden yükleyin. Dosya bozulduysa betiği yeniden çalıştırın."),
        "bicim": ("Dosya kabul edilmedi", "Dosyanın içeriği beklenen biçime uymuyor. Dosya elle değiştirilmiş olabilir.",
                  "Betiği yeniden çalıştırın ve yazdığı dosyayı değiştirmeden yükleyin."),
        "eski": ("Betik sürümü eski", "Bu dosya toplayıcı betiğin eski bir sürümüyle üretilmiş.",
                 "Güncel betiği tarama sayfasından indirin, SHA-256 özetini doğrulayın ve yeniden çalıştırın."),
        "buyuk": ("Dosya çok büyük", "Toplama dosyası 5 MB sınırını aşıyor.",
                  "Betiğin yazdığı dosyayı değiştirmeden yükleyin. Sorun sürerse bize yazın."),
        "tur": ("İstek anlaşılamadı", "Dosya beklenen biçimde gönderilmedi.",
                "Dosyayı tarama sayfasındaki formu kullanarak yükleyin."),
        "pasif": ("Hesabınız şu an etkin değil", "Şirketinizin kaydı geçici olarak kapatılmış, yeni tarama yüklenemiyor. Mevcut raporlarınız etkilenmez.",
                  "Kaydınızın yeniden açılması için bizimle iletişime geçin."),
        "sinir": ("Ücretsiz tarama hakkınız doldu", "Şirket başına {gun} günde {adet} ücretsiz tarama yapılır ve bu dönemdeki hakkınız kullanıldı. Bu yükleme kaydedilmedi.",
                  "Daha erken bir tarama ya da kapsamlı bir denetim için bizimle iletişime geçin."),
        "hiz": ("Çok fazla deneme", "Bu adresten kısa sürede çok sayıda yükleme yapıldı.",
                "Bir saat sonra yeniden deneyin."),
        "izin": ("Doğrudan bağlantı hesabınız için açık değil", "Doğrudan bağlantıyla tarama yalnızca alig.tech tarafından onaylanmış şirketlere açıktır.",
                 "Onay için bizimle iletişime geçin ya da betiği kendi ağınızda çalıştırıp dosyayı yükleyin."),
        "hedef": ("Sunucuya bağlanılamadı", "Bu sunucuya bağlanılamadı. Yalnızca internetten erişilebilen adresler kabul edilir.",
                  "Adresi, portu, veritabanı ve hesap adını denetleyip yeniden deneyin."),
        "baglanti": ("Sunucuya bağlanılamadı", "Bağlantı kurulamadı ya da hesap bilgileri kabul edilmedi. Bağlantı şifreli (TLS) olmalı ve tarama hesabı SCRAM-SHA-256 ile doğrulanmalıdır.",
                     "Parolayı, güvenlik duvarı iznini ve sunucunun TLS ayarını denetleyip yeniden deneyin."),
        "kanit": ("Sahiplik kanıtı bulunamadı", "Tarama hesabının üzerinde beklenen kanıt satırı yok ya da farklı. Hiçbir denetim sorgusu çalıştırılmadı.",
                  "Önceki sayfadaki COMMENT komutunu veritabanınızda çalıştırın, sonra parolayı yeniden gönderin."),
        "super": ("Bu hesapla tarama yapılmaz", "Verdiğiniz hesap süper kullanıcı. Doğrudan bağlantıda süper kullanıcı kabul edilmez. Hiçbir denetim sorgusu çalıştırılmadı.",
                  "Hazırlık kılavuzundaki alig_hc hesabını açıp onunla yeniden deneyin."),
        "zaman": ("Tarama zamanında bitmedi", "Sunucu süre sınırı içinde yanıt vermedi.",
                  "Bir süre sonra yeniden deneyin ya da betiği kendi ağınızda çalıştırın."),
        "istek_yok": ("Bu bağlantı isteği geçersiz", "İsteğin süresi dolmuş, kullanılmış ya da hiç var olmamış. İstekler 30 dakika geçerlidir.",
                      "Doğrudan bağlantı formunu yeniden doldurun."),
        "deneme": ("Deneme hakkı doldu", "Bu istek için üç deneme hakkı kullanıldı ya da şirketiniz son bir saatte çok sayıda istek açtı.",
                   "Bilgileri denetleyip bir saat sonra yeni bir istek açın."),
        "mesgul": ("Şu an çok sayıda tarama çalışıyor", "Aynı anda çalışan tarama sayısı sınırına ulaşıldı.",
                   "Birkaç dakika sonra parolayı yeniden gönderin."),
        "posta": ("Çok sayıda bağlantı gönderildi", "Bu adrese ya da şirketinize son 24 saatte çok sayıda rapor bağlantısı gönderildi. Bu yükleme kaydedilmedi.",
                  "Gelen kutunuzu ve istenmeyen klasörünü kontrol edin ya da 24 saat sonra yeniden deneyin."),
    },
    "en": {
        "ust": "Health check", "ne": "What to do", "teknik": "Technical detail",
        "geri": "Back to the health check page", "kilavuz": "Open the preparation guide", "iletisim": "Contact us",
        "yetki": ("Authorisation statement missing", "To upload the file you need to tick \"I am authorised to have this database scanned\".",
                  "Go back to the health check page, tick the box and upload the file again."),
        "eposta": ("Email address not valid", "The email address you entered was not recognised.",
                   "Enter your corporate email address in the form name@company.com and try again."),
        "sirket": ("Company name missing", "The company name is empty or longer than 160 characters.",
                   "Enter your company name and upload the file again."),
        "json": ("File could not be read", "The file you uploaded is not a valid collection file.",
                 "Upload the alig-toplama.json file written by the script without changing it. If the file is damaged, run the script again."),
        "bicim": ("File not accepted", "The contents of the file do not match the expected format. The file may have been edited by hand.",
                  "Run the script again and upload the file it writes without changing it."),
        "eski": ("Script version is old", "This file was produced by an old version of the collector script.",
                 "Download the current script from the health check page, verify its SHA-256 digest and run it again."),
        "buyuk": ("File too large", "The collection file is over the 5 MB limit.",
                  "Upload the file written by the script without changing it. If the problem continues, contact us."),
        "tur": ("Request not understood", "The file was not sent in the expected form.",
                "Upload the file using the form on the health check page."),
        "pasif": ("Your account is not active right now", "Your company's registration is temporarily closed, so new scans cannot be uploaded. Your existing reports are not affected.",
                  "Contact us to have your registration reopened."),
        "sinir": ("Your free scans are used up", "Each company gets {adet} free scans per {gun} days and yours are used for this period. This upload was not saved.",
                  "Contact us for an earlier scan or a full audit."),
        "hiz": ("Too many attempts", "Many uploads were made from this address in a short time.",
                "Try again in an hour."),
        "izin": ("Direct connection is not open for your account", "Scanning over a direct connection is open only to companies approved by alig.tech.",
                 "Contact us for approval, or run the script on your own network and upload the file."),
        "hedef": ("Could not connect to the server", "Could not connect to this server. Only addresses reachable from the internet are accepted.",
                  "Check the address, port, database and account name, then try again."),
        "baglanti": ("Could not connect to the server", "The connection failed or the account details were not accepted. The connection must be encrypted (TLS) and the scan account must authenticate with SCRAM-SHA-256.",
                     "Check the password, the firewall rule and the server's TLS setting, then try again."),
        "kanit": ("Ownership proof not found", "The expected proof line is missing from the scan account, or it differs. No check query was run.",
                  "Run the COMMENT command from the previous page on your database, then send the password again."),
        "super": ("This account cannot be used for scanning", "The account you gave is a superuser. Superusers are not accepted over a direct connection. No check query was run.",
                  "Open the alig_hc account from the preparation guide and try again with it."),
        "zaman": ("The scan did not finish in time", "The server did not answer within the time limit.",
                  "Try again later, or run the script on your own network."),
        "istek_yok": ("This connection request is not valid", "The request has expired, was already used or never existed. Requests are valid for 30 minutes.",
                      "Fill in the direct connection form again."),
        "deneme": ("No attempts left", "The three attempts for this request are used, or your company opened many requests in the last hour.",
                   "Check the details and open a new request in an hour."),
        "mesgul": ("Many scans are running right now", "The limit on scans running at the same time has been reached.",
                   "Send the password again in a few minutes."),
        "posta": ("Too many links sent", "Many report links were sent to this address or your company in the last 24 hours. This upload was not saved.",
                  "Check your inbox and spam folder, or try again in 24 hours."),
    },
}

# Dosya dogrulama kodu -> (sayfa turu, tr ayrinti, en ayrinti). {ek}: kontrol ya da alan adi.
TEKNIK = {
    "buyuk": ("buyuk", "", ""),
    "json": ("json", "dosya geçerli JSON değil", "the file is not valid JSON"),
    "eski": ("eski", "sorgu kataloğu özeti güncel betikle uyuşmuyor", "the query catalogue digest does not match the current script"),
    "alanlar": ("bicim", "üst düzey alanlar beklenenle uyuşmuyor", "top-level fields do not match what is expected"),
    "format": ("bicim", "dosya biçimi ya da veritabanı motoru desteklenmiyor", "file format or database engine is not supported"),
    "motor_kapali": ("bicim", "bu veritabanı motoru için tarama henüz açık değil", "scanning is not open yet for this database engine"),
    "derin": ("bicim", "dosyadaki iç içe yapı beklenenden derin", "the nested structure in the file is deeper than expected"),
    "zaman": ("bicim", "oluşturma zamanı geçersiz", "creation time is not valid"),
    "alan_turu": ("bicim", "{ek}: alan türü geçersiz", "{ek}: field type is not valid"),
    "kontrol": ("bicim", "bilinmeyen denetim: {ek}", "unknown check: {ek}"),
    "durum": ("bicim", "{ek}: durum değeri geçersiz", "{ek}: status value is not valid"),
    "hata_kaydi": ("bicim", "{ek}: hata kaydı geçersiz", "{ek}: error record is not valid"),
    "satirlar": ("bicim", "{ek}: satır listesi geçersiz ya da çok uzun", "{ek}: row list is not valid or too long"),
    "kolon": ("bicim", "{ek}: bilinmeyen kolon", "{ek}: unknown column"),
    "deger": ("bicim", "{ek}: değer türü ya da uzunluğu geçersiz", "{ek}: value type or length is not valid"),
    "bicim": ("bicim", "", ""),
}


def dosya_hatasi(kod, ek, dil):
    """(sayfa turu, musteri dilinde teknik ayrinti) dondurur."""
    tur, tr, en = TEKNIK.get(kod, TEKNIK["bicim"])
    metin = en if dil == "en" else tr
    return tur, metin.replace("{ek}", str(ek)[:60])


ILETISIM = {"pasif", "sinir", "buyuk", "izin", "posta"}
KILAVUZ = {"json", "bicim", "eski", "tur", "kanit", "super", "zaman", "baglanti"}
DOGRUDAN = {"hedef", "baglanti", "istek_yok", "deneme", "zaman"}

F = {
    "tr": {"baslik": "Doğrudan bağlantıyla tarama", "lead": "Bağlantı bilgisini verirsiniz, taramayı alig.tech çalıştırır. Parolanız saklanmaz, yalnızca tarama süresince kullanılır.",
           "sirket": "Şirket adı", "eposta": "Kurumsal e-posta adresiniz", "sunucu": "Sunucu adresi (internetten erişilebilir ad ya da IP)",
           "port": "Port", "veritabani": "Veritabanı", "kullanici": "Tarama hesabı", "maskele": "Nesne adlarını takma adla değiştir",
           "yetki": "Bu veritabanını taratmaya yetkiliyim.", "gonder": "Devam et",
           "not": "Hesap süper kullanıcı olmamalı ve bağlantı TLS ile şifreli olmalıdır. Hesabı açmak için hazırlık kılavuzuna bakın.",
           "k_baslik": "Sahipliği kanıtlayın", "k_lead": "Bu veritabanının sizin yönetiminizde olduğunu göstermek için aşağıdaki komutu veritabanınızda bir kez çalıştırın. Sonra tarama hesabının parolasını yazın.",
           "k_sure": "Bu istek 30 dakika geçerlidir ve en çok üç kez denenebilir.", "parola": "Tarama hesabının parolası",
           "k_not": "Parola saklanmaz, günlüklere yazılmaz ve tarama bitince bellekten silinir. Tarama bir dakikadan uzun sürebilir.", "baslat": "Taramayı başlat"},
    "en": {"baslik": "Scan over a direct connection", "lead": "You give the connection details and alig.tech runs the scan. Your password is not stored; it is used only while the scan runs.",
           "sirket": "Company name", "eposta": "Your corporate email address", "sunucu": "Server address (name or IP reachable from the internet)",
           "port": "Port", "veritabani": "Database", "kullanici": "Scan account", "maskele": "Replace object names with aliases",
           "yetki": "I am authorised to have this database scanned.", "gonder": "Continue",
           "not": "The account must not be a superuser and the connection must be encrypted with TLS. See the preparation guide to open the account.",
           "k_baslik": "Prove ownership", "k_lead": "To show that this database is under your administration, run the command below once on your database. Then enter the password of the scan account.",
           "k_sure": "This request is valid for 30 minutes and can be tried at most three times.", "parola": "Password of the scan account",
           "k_not": "The password is not stored, not written to logs and is cleared from memory when the scan ends. The scan can take over a minute.", "baslat": "Start the scan"},
}


def _kabuk(d, baslik, icerik):
    kok = "/en/" if d == "en" else "/"
    return ("<!doctype html>\n<html lang=\"%s\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex,nofollow\"><title>%s | alig.tech</title>"
            "<link rel=\"stylesheet\" href=\"/assets/base.css\"><link rel=\"stylesheet\" href=\"/assets/style.css\"></head><body>"
            "<header class=\"top\"><div class=\"wrap\"><a class=\"brand\" href=\"%s\"><img src=\"/assets/logo.svg\" width=\"176\" height=\"36\" alt=\"alig.tech\"></a></div></header>"
            "<main id=\"main\">%s</main></body></html>\n") % (d, escape(baslik), kok, icerik)


def baglan_formu(dil):
    d = dil if dil in F else "tr"
    f = F[d]
    kok = "/en/" if d == "en" else "/"

    def alan(ad, etiket, tur="text", deger="", ek=""):
        return ("<div class=\"field field-wide\"><label for=\"b-%s\">%s</label><input id=\"b-%s\" name=\"%s\" type=\"%s\" value=\"%s\" required %s></div>"
                % (ad, escape(etiket), ad, ad, tur, escape(deger), ek))
    icerik = ("<article class=\"wrap prose tarama-page\"><h1>%s</h1><p class=\"lead\">%s</p>"
              "<form class=\"form\" method=\"post\" action=\"/api/tarama/baglan\"><input type=\"hidden\" name=\"dil\" value=\"%s\">%s%s%s%s%s%s"
              "<div class=\"field field-wide\"><label for=\"b-mask\"><input id=\"b-mask\" type=\"checkbox\" name=\"maskele\" value=\"on\" checked> %s</label></div>"
              "<div class=\"field field-wide\"><label for=\"b-ok\"><input id=\"b-ok\" type=\"checkbox\" name=\"yetki\" value=\"on\" required> %s</label></div>"
              "<p class=\"form-foot\"><button class=\"btn\" type=\"submit\">%s</button></p></form>"
              "<p class=\"fine\">%s <a href=\"%starama-hazirlik/\">%s</a></p></article>") % (
        escape(f["baslik"]), escape(f["lead"]), d,
        alan("sirket", f["sirket"], ek="maxlength=\"160\" autocomplete=\"organization\""),
        alan("eposta", f["eposta"], "email", ek="maxlength=\"200\" autocomplete=\"email\""),
        alan("sunucu", f["sunucu"], ek="maxlength=\"253\" autocomplete=\"off\""),
        alan("port", f["port"], "number", "5432", "min=\"1024\" max=\"65535\""),
        alan("veritabani", f["veritabani"], deger="postgres", ek="maxlength=\"63\" autocomplete=\"off\""),
        alan("kullanici", f["kullanici"], deger="alig_hc", ek="maxlength=\"63\" autocomplete=\"off\""),
        escape(f["maskele"]), escape(f["yetki"]), escape(f["gonder"]), escape(f["not"]), kok, escape(M[d]["kilavuz"]))
    return _kabuk(d, f["baslik"], icerik)


def kanit_sayfasi(dil, token, komut):
    d = dil if dil in F else "tr"
    f = F[d]
    icerik = ("<article class=\"wrap prose tarama-page guide\"><h1>%s</h1><p class=\"lead\">%s</p><pre><code>%s</code></pre><p class=\"fine\">%s</p>"
              "<form class=\"form\" method=\"post\" action=\"/api/tarama/baglan/%s\" autocomplete=\"off\">"
              "<div class=\"field field-wide\"><label for=\"b-parola\">%s</label>"
              "<input id=\"b-parola\" name=\"parola\" type=\"password\" required maxlength=\"1024\" autocomplete=\"off\"></div>"
              "<p class=\"form-foot\"><button class=\"btn\" type=\"submit\">%s</button></p></form><p class=\"fine\">%s</p></article>") % (
        escape(f["k_baslik"]), escape(f["k_lead"]), escape(komut), escape(f["k_sure"]), escape(token),
        escape(f["parola"]), escape(f["baslat"]), escape(f["k_not"]))
    return _kabuk(d, f["k_baslik"], icerik)


def sayfa(tur, dil, ayrinti=None):
    d = dil if dil in M else "tr"
    m = M[d]
    baslik, ne_oldu, ne_yapmali = m[tur]
    from tarama import depo   # sinir metni sabitten: SINIR_ADET ya da SINIR_GUN degisirse sayfa da degisir
    ne_oldu = ne_oldu.replace("{adet}", str(depo.SINIR_ADET)).replace("{gun}", str(depo.SINIR_GUN))
    kok = "/en/" if d == "en" else "/"
    if tur in DOGRUDAN:
        baglar = ['<a class="btn" href="/api/tarama/baglan?dil=%s">%s</a>' % (d, escape(F[d]["baslik"]))]
    else:
        baglar = ['<a class="btn" href="%ssaglik-taramasi/">%s</a>' % (kok, escape(m["geri"]))]
    if tur in KILAVUZ:
        baglar.append('<a class="textlink" href="%starama-hazirlik/">%s</a>' % (kok, escape(m["kilavuz"])))
    if tur in ILETISIM:
        baglar.append('<a class="textlink" href="%s#iletisim">%s</a>' % (kok, escape(m["iletisim"])))
    teknik = ""
    if ayrinti:
        teknik = '<p class="fine">%s: <code>%s</code></p>' % (escape(m["teknik"]), escape(str(ayrinti)[:200]))
    icerik = ('<article class="wrap prose tarama-page"><p class="fine">%s</p><h1>%s</h1><p class="lead">%s</p>'
              '<h2>%s</h2><p>%s</p>%s<p>%s</p></article>') % (
        escape(m["ust"]), escape(baslik), escape(ne_oldu), escape(m["ne"]), escape(ne_yapmali), teknik, " ".join(baglar))
    return _kabuk(d, baslik, icerik)


D = {
    "tr": {"g_baslik": "E-postanızı kontrol edin",
           "g_lead": "Raporun bağlantısını %s adresine gönderdik. Bağlantı %d saat geçerlidir.",
           "g_ne": "E-postadaki bağlantıyı açın ve sayfadaki düğmeyle raporu açın. Ücretsiz tarama hakkınız bu adımda kullanılır. "
                   "E-posta birkaç dakika içinde gelmezse istenmeyen klasörünü kontrol edin.",
           "o_baslik": "Raporunuz hazır",
           "o_lead": "E-posta adresinizi doğrulamak ve raporu açmak için düğmeye basın. Ücretsiz tarama hakkınız bu adımda kullanılır.",
           "o_dugme": "E-postamı doğrula ve raporu aç",
           "o_not": "Bu yüklemeyi siz yapmadıysanız sayfayı kapatın. Doğrulanmayan rapor kendiliğinden silinir."},
    "en": {"g_baslik": "Check your email",
           "g_lead": "We sent the link to your report to %s. The link is valid for %d hours.",
           "g_ne": "Open the link in the email and open the report with the button on the page. Your free scan allowance is used at that step. "
                   "If the email does not arrive in a few minutes, check your spam folder.",
           "o_baslik": "Your report is ready",
           "o_lead": "Press the button to confirm your email address and open the report. Your free scan allowance is used at this step.",
           "o_dugme": "Confirm my email and open the report",
           "o_not": "If you did not make this upload, close this page. A report that is not confirmed is deleted automatically."},
}


def dogrulama_gonderildi(dil, eposta, saat):
    """Yukleme sonrasi: baglanti e-postayla gitti. Sayfada baglanti YOK."""
    d = dil if dil in D else "tr"
    t, kok = D[d], ("/en/" if d == "en" else "/")
    icerik = ('<article class="wrap prose tarama-page"><p class="fine">%s</p><h1>%s</h1><p class="lead">%s</p><p>%s</p>'
              '<p><a class="textlink" href="%starama-hazirlik/">%s</a></p></article>') % (
        escape(M[d]["ust"]), escape(t["g_baslik"]), escape(t["g_lead"] % (eposta, saat)), escape(t["g_ne"]), kok, escape(M[d]["kilavuz"]))
    return _kabuk(d, t["g_baslik"], icerik)


def dogrulama_onay(dil, token):
    """E-postadaki baglanti: GET hicbir sey degistirmez (e-posta tarayicilari baglantiyi kendiliginden acar);
    dogrulama yalniz dugmeyle (POST) olur."""
    d = dil if dil in D else "tr"
    t = D[d]
    icerik = ('<article class="wrap prose tarama-page"><p class="fine">%s</p><h1>%s</h1><p class="lead">%s</p>'
              '<form method="post" action="/rapor/%s/dogrula"><p><button class="btn" type="submit">%s</button></p></form>'
              '<p class="fine">%s</p></article>') % (
        escape(M[d]["ust"]), escape(t["o_baslik"]), escape(t["o_lead"]), escape(token), escape(t["o_dugme"]), escape(t["o_not"]))
    return _kabuk(d, t["o_baslik"], icerik)


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
        "sinir": ("Ücretsiz tarama hakkınız doldu", "Şirket başına 30 günde 2 ücretsiz tarama yapılır ve bu dönemdeki hakkınız kullanıldı. Bu yükleme kaydedilmedi.",
                  "Daha erken bir tarama ya da kapsamlı bir denetim için bizimle iletişime geçin."),
        "hiz": ("Çok fazla deneme", "Bu adresten kısa sürede çok sayıda yükleme yapıldı.",
                "Bir saat sonra yeniden deneyin."),
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
        "sinir": ("Your free scans are used up", "Each company gets 2 free scans per 30 days and yours are used for this period. This upload was not saved.",
                  "Contact us for an earlier scan or a full audit."),
        "hiz": ("Too many attempts", "Many uploads were made from this address in a short time.",
                "Try again in an hour."),
    },
}

ILETISIM = {"pasif", "sinir", "buyuk"}
KILAVUZ = {"json", "bicim", "eski", "tur"}


def dosya_turu(neden):
    """yukleme.Gecersiz mesajini musteri diline cevrilecek anahtara esler."""
    n = neden or ""
    if "cok buyuk" in n:
        return "buyuk"
    if "surumu eski" in n:
        return "eski"
    if "JSON" in n:
        return "json"
    return "bicim"


def sayfa(tur, dil, ayrinti=None):
    d = dil if dil in M else "tr"
    m = M[d]
    baslik, ne_oldu, ne_yapmali = m[tur]
    kok = "/en/" if d == "en" else "/"
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
    return ("<!doctype html>\n<html lang=\"%s\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex,nofollow\"><title>%s | alig.tech</title>"
            "<link rel=\"stylesheet\" href=\"/assets/base.css\"><link rel=\"stylesheet\" href=\"/assets/style.css\"></head><body>"
            "<header class=\"top\"><div class=\"wrap\"><a class=\"brand\" href=\"%s\"><img src=\"/assets/logo.svg\" width=\"176\" height=\"36\" alt=\"alig.tech\"></a></div></header>"
            "<main id=\"main\">%s</main></body></html>\n") % (d, escape(baslik), kok, icerik)

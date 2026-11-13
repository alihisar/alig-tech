"""Rapor HTML'i. Tum degerler html.escape ile yazilir; nesne adlari yalniz kanit listesinde gorunur."""
from html import escape

from tarama import kanit, katalog, kurallar

M = {
    "tr": {"baslik": "Sağlık taraması raporu", "ozet": "Özet", "tarama": "Tarama zamanı (UTC)", "motor": "Motor",
           "surum": "Maskeli", "evet": "evet", "hayir": "hayır", "bulgu": "Bulgular", "yok": "Bu taramada bulgu çıkmadı.",
           "kanit": "Kanıt", "neden": "Neden önemli", "oneri": "Öneri", "risk": "Önerinin riski", "geri": "Geri alma",
           "is": "İş büyüklüğü", "denetimler": "Denetimler", "sonuclar": "Denetim sonuçları",
           "sonuclar_a": "Her denetim bir durum alır. Bilinmiyor ve Alınamadı temiz demek değildir: o denetim için yeterli veri gelmedi.",
           "basliklar": ("Kural", "Denetim", "Kategori", "Durum", "Güven", "Ölçüm ve not"),
           "kural": "Kural", "kaynak": "Kaynak", "guven": "Kanıt güveni", "durum_e": "Durum",
           "durum": {"FAIL": "Başarısız", "WARNING": "Uyarı", "UNKNOWN": "Bilinmiyor", "UNAVAILABLE": "Alınamadı",
                     "NOT_APPLICABLE": "Uygulanmaz", "PASS": "Geçti"},
           "guven_d": {"HIGH": "yüksek", "MEDIUM": "orta", "LOW": "düşük"},
           "kategori": {"guvenlik": "Güvenlik", "performans": "Performans", "konfigurasyon": "Konfigürasyon", "bakim": "Bakım",
                        "kapasite": "Kapasite", "ha_dr": "HA/DR", "yedek": "Yedekleme"},
           "kapsam": "Bu tarama neye bakmaz",
           "kapsam_l": ["Yedekten geri dönüşün gerçekten çalıştığı", "İşletim sistemi ve ağ ayarları", "Uygulama sorguları ve yük altındaki davranış", "Veri içeriği"],
           "uyari": "Bu rapor tavsiye niteliğindedir. Hiçbir değişiklik uygulanmamıştır.",
           "onsurum": "SQL Server taraması ön sürümdür. Bulguları uygulamadan önce kendi ortamınızda doğrulayın.",
           "sil": "Raporu şimdi sil", "bitis": "Rapor şu tarihte otomatik silinir (UTC)", "cta": "Denetim iste", "ana": "alig.tech",
           "onem": {"kritik": "Kritik", "yuksek": "Yüksek", "orta": "Orta", "dusuk": "Düşük", "bilgi": "Bilgi"},
           "isb": {"kucuk": "küçük", "orta": "orta", "buyuk": "büyük"},
           "nedenler": {"yetki": "yetki yok", "zaman_asimi": "zaman aşımı", "desteklenmiyor": "bu sürümde desteklenmiyor",
                        "yedek_sunucu": "yedek sunucuda çalışmaz", "hata": "hata", "calistirilmadi": "çalıştırılmadı",
                        "gecersiz_veri": "değer biçimi geçersiz",
                        "kismi_yetki": "kısmen ölçüldü: bazı sequence değerleri tarama hesabının yetkisiyle okunamadı",
                        "kismi_veritabani": "kısmen ölçüldü: sunucudaki bazı veritabanları taranmadı", "sinir": "veritabanı sayısı sınırı",
                        "ad": "veritabanı adı desteklenmiyor", "eksik_veri": "veri eksik", "slot_yok": "replikasyon slotu yok",
                        "ag_yok": "Always On kullanılmıyor", "yonetilen_hizmet": "yönetilen hizmet: sürümü Microsoft yönetir",
                        "tcp_baglanti_yok": "tarama anında TCP bağlantısı yok", "arsiv_kaniti_yok": "başarılı arşivleme kaydı yok",
                        "rol_eksik": "kısmen ölçüldü: tarama hesabında gereken rol yok (pg_monitor)",
                        "rol_bilinmiyor": "kısmen ölçüldü: tarama hesabının yetkileri okunamadı"},
           "sunucu": "Sunucu sürümü", "sinandi": "bu sürümde sınandı",
           "sinanmadi": "bu sürüm araçla henüz sınanmadı; kanıt güveni en çok orta gösterilir", "bilinmiyor_s": "bilinmiyor",
           "db": "Tablo, indeks ve sequence denetimleri",
           "db_d": "%d veritabanında çalıştı (sunucuda %d)",
           "db_a": "Atlanan veritabanları",
           "db_k": "Atlanan %d veritabanında tablo, indeks ve sequence durumu. Tarama hesabına bağlanma yetkisi verin ya da betiği --veritabanlari ile o veritabanları için çalıştırın."},
    "en": {"baslik": "Health check report", "ozet": "Summary", "tarama": "Scan time (UTC)", "motor": "Engine",
           "surum": "Masked", "evet": "yes", "hayir": "no", "bulgu": "Findings", "yok": "No findings in this scan.",
           "kanit": "Evidence", "neden": "Why it matters", "oneri": "Proposal", "risk": "Risk of the proposal", "geri": "Rollback",
           "is": "Effort", "denetimler": "Checks", "sonuclar": "Check results",
           "sonuclar_a": "Every check gets a status. Unknown and Unavailable do not mean clean: not enough data arrived for that check.",
           "basliklar": ("Rule", "Check", "Category", "Status", "Confidence", "Measurement and note"),
           "kural": "Rule", "kaynak": "Source", "guven": "Evidence confidence", "durum_e": "Status",
           "durum": {"FAIL": "Fail", "WARNING": "Warning", "UNKNOWN": "Unknown", "UNAVAILABLE": "Unavailable",
                     "NOT_APPLICABLE": "Not applicable", "PASS": "Pass"},
           "guven_d": {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"},
           "kategori": {"guvenlik": "Security", "performans": "Performance", "konfigurasyon": "Configuration", "bakim": "Maintenance",
                        "kapasite": "Capacity", "ha_dr": "HA/DR", "yedek": "Backup"},
           "kapsam": "What this scan does not look at",
           "kapsam_l": ["Whether a restore from backup really works", "Operating system and network settings", "Application queries and behaviour under load", "Data contents"],
           "uyari": "This report is advisory. No changes have been applied.",
           "onsurum": "The SQL Server scan is a preview. Verify findings in your own environment before acting on them.",
           "sil": "Delete report now", "bitis": "Report is deleted automatically on (UTC)", "cta": "Request an audit", "ana": "alig.tech",
           "onem": {"kritik": "Critical", "yuksek": "High", "orta": "Medium", "dusuk": "Low", "bilgi": "Info"},
           "isb": {"kucuk": "small", "orta": "medium", "buyuk": "large"},
           "nedenler": {"yetki": "no permission", "zaman_asimi": "timeout", "desteklenmiyor": "not supported on this version",
                        "yedek_sunucu": "does not run on a standby", "hata": "error", "calistirilmadi": "not run",
                        "gecersiz_veri": "invalid value format",
                        "kismi_yetki": "partially measured: some sequence values could not be read with the scan account's privileges",
                        "kismi_veritabani": "partially measured: some databases on the server were not scanned", "sinir": "database count limit",
                        "ad": "database name not supported", "eksik_veri": "data incomplete", "slot_yok": "no replication slots",
                        "ag_yok": "Always On is not in use", "yonetilen_hizmet": "managed service: Microsoft manages the version",
                        "tcp_baglanti_yok": "no TCP connections at scan time", "arsiv_kaniti_yok": "no successful archiving recorded",
                        "rol_eksik": "partially measured: the scan account lacks the required role (pg_monitor)",
                        "rol_bilinmiyor": "partially measured: the scan account's privileges could not be read"},
           "sunucu": "Server version", "sinandi": "tested on this version",
           "sinanmadi": "this version has not been tested with the tool yet; evidence confidence is shown as medium at most", "bilinmiyor_s": "unknown",
           "db": "Table, index and sequence checks",
           "db_d": "ran in %d databases (%d on the server)",
           "db_a": "Skipped databases",
           "db_k": "Table, index and sequence state in the %d skipped databases. Grant the scan account permission to connect, or run the script with --veritabanlari for those databases."},
}


def _kanit(kanit):
    out = []
    for k, v in kanit.items():
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        out.append("<li><code>%s</code>: %s</li>" % (escape(str(k)), escape(str(v))))
    return "<ul class=\"ev\">%s</ul>" % "".join(out)


def _db(belge):
    """(taranan veritabani sayisi, sunucudaki veritabani sayisi, [(atlanan ad, neden)]) ya da None. Bozuk degerde None."""
    e = (belge.get("kontroller") or {}).get("pg_kapsam")
    try:
        if e["durum"] != "ok" or not e["satirlar"]:
            return None
        toplam = e["satirlar"][0]["veritabani_sayisi"]
        if not isinstance(toplam, int) or isinstance(toplam, bool):
            return None
        atlanan = [(str(x["veritabani"]), str(x["neden"])) for x in e.get("atlanan") or []]
        return len(e["satirlar"]), toplam, atlanan
    except (TypeError, KeyError, IndexError):
        return None


def _kapsam(belge, m):
    db = _db(belge)
    if not db:
        return ""
    out = "<dt>%s</dt><dd>%s</dd>" % (escape(m["db"]), escape(m["db_d"] % (db[0], db[1])))
    if db[2]:
        out += "<dt>%s</dt><dd>%s</dd>" % (escape(m["db_a"]), escape(", ".join("%s (%s)" % (ad, m["nedenler"].get(n, n)) for ad, n in db[2][:20])))
    return out


def _deger(v, m):
    if v is True:
        return m["evet"]
    if v is False:
        return m["hayir"]
    return "-" if v is None else str(v)


def _not(k, m):
    """Durum tablosundaki olcum ve not: gozlenen degerler ve UNKNOWN, UNAVAILABLE, NOT_APPLICABLE nedeni."""
    parcalar = ["<code>%s</code>: %s" % (escape(str(a)), escape(_deger(v, m))) for a, v in k["gozlem"].items()]
    if k["neden"]:
        parcalar.append(escape(m["nedenler"].get(k["neden"], k["neden"])))
    return ", ".join(parcalar) or "-"


def _surum(s, motor, m):
    """PostgreSQL ana surumu ve sorgularin o surumde gercek sunucuda sinanip sinanmadigi."""
    if motor != "postgresql":
        return ""
    ana = s.baglam.get("ana_surum")
    metin = ("PostgreSQL %d: %s" % (ana, m["sinandi"] if s.baglam.get("sinanan") else m["sinanmadi"])) if ana else \
        "%s: %s" % (m["bilinmiyor_s"], m["sinanmadi"])
    return "<dt>%s</dt><dd>%s</dd>" % (escape(m["sunucu"]), escape(metin))


def _durumlar(s, m, d):
    sira = sorted(s.kayitlar, key=lambda k: (kanit.KATEGORILER.index(k["kategori"]), k["kural"]))
    satirlar = []
    for k in sira:
        hucre = (k["ad"][d], m["kategori"][k["kategori"]], m["durum"][k["durum"]], m["guven_d"].get(k["guven"], "-"))
        satirlar.append("<tr><th scope=\"row\"><code>%s</code></th>%s<td data-label=\"%s\">%s</td></tr>" % (
            escape(k["kural"]), "".join("<td data-label=\"%s\">%s</td>" % (escape(b), escape(h)) for b, h in zip(m["basliklar"][1:5], hucre)),
            escape(m["basliklar"][5]), _not(k, m)))
    return ("<h2>%s</h2><p>%s</p><table class=\"tiers durumlar\"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
        escape(m["sonuclar"]), escape(m["sonuclar_a"]), "".join("<th scope=\"col\">%s</th>" % escape(b) for b in m["basliklar"]),
        "".join(satirlar)))


def govde(rapor, dil, token, eylemler=True):
    m = M[dil if dil in M else "tr"]
    d = dil if dil in M else "tr"
    belge = rapor["belge"]
    sonuc = kurallar.incele(belge)
    bulgu, olcul = sonuc.bulgular, sonuc.olculemeyen
    sayim = {o: sum(1 for b in bulgu if b["onem"] == o) for o in kurallar.ONEM}
    durum_sayim = sonuc.sayim()
    motor = belge.get("motor", "postgresql")
    p = ["<article class=\"wrap prose report\">", "<h1>%s</h1>" % escape(m["baslik"]), "<p>%s</p>" % escape(m["uyari"]),
         "<p><strong>%s</strong></p>" % escape(m["onsurum"]) if motor == "mssql" else "",
         "<h2>%s</h2>" % escape(m["ozet"]), "<dl class=\"facts\">",
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["tarama"]), escape(belge["olusturma_utc"])),
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["motor"]), escape(katalog.MOTOR_AD.get(motor, motor))),
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["surum"]), escape(m["evet"] if belge.get("maskeli") else m["hayir"])),
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["bulgu"]), escape(", ".join("%s: %d" % (m["onem"][o], n) for o, n in sayim.items() if n) or m["yok"])),
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["denetimler"]), escape(", ".join("%s: %d" % (m["durum"][x], n) for x, n in durum_sayim.items() if n))),
         _surum(sonuc, motor, m), _kapsam(belge, m), "</dl>", "<h2>%s</h2>" % escape(m["bulgu"])]
    for b in bulgu:
        p.append("<section class=\"finding-card sev-%s\"><h3>%s: %s</h3>" % (escape(b["onem"]), escape(m["onem"][b["onem"]]), escape(b["baslik"][d])))
        p.append("<p><strong>%s.</strong> %s (%s). %s: %s. %s: %s.</p>" % (
            escape(m["kural"]), escape(b["kural"]), escape(m["kategori"][b["kategori"]]), escape(m["durum_e"]), escape(m["durum"][b["durum"]]),
            escape(m["guven"]), escape(m["guven_d"][b["guven"]])))
        for anahtar, etiket in (("neden", "neden"), ("oneri", "oneri"), ("risk", "risk"), ("geri_alma", "geri")):
            p.append("<p><strong>%s.</strong> %s</p>" % (escape(m[etiket]), escape(b[anahtar][d])))
        p.append("<p><strong>%s.</strong> %s</p>" % (escape(m["is"]), escape(m["isb"][b["is"]])))
        p.append("<p><strong>%s.</strong> %s</p>" % (escape(m["kaynak"]), ", ".join("<code>%s</code>" % escape(x) for x in b["kaynak"])))
        p.append("<p><strong>%s.</strong></p>%s</section>" % (escape(m["kanit"]), _kanit(b["kanit"])))
    p.append(_durumlar(sonuc, m, d))
    kapsam_l = list(m["kapsam_l"])
    db = _db(belge)
    if db and db[2]:
        kapsam_l.insert(0, m["db_k"] % len(db[2]))
    p.append("<h2>%s</h2><ul class=\"plain\">%s</ul>" % (escape(m["kapsam"]), "".join("<li>%s</li>" % escape(x) for x in kapsam_l)))
    p.append("<p>%s: %s</p>" % (escape(m["bitis"]), escape(rapor["bitis_utc"])))
    if not eylemler:
        p.append("</article>")
        return "\n".join(p), bulgu, olcul
    p.append("<form method=\"post\" action=\"/rapor/%s/sil\"><button class=\"btn btn-ghost\" type=\"submit\">%s</button></form>" % (escape(token), escape(m["sil"])))
    p.append("<p><a class=\"btn\" href=\"%s#iletisim\">%s</a></p></article>" % ("/en/" if d == "en" else "/", escape(m["cta"])))
    return "\n".join(p), bulgu, olcul


def sayfa(rapor, dil, token):
    d = dil if dil in M else "tr"
    icerik, _, _ = govde(rapor, d, token)
    return ("<!doctype html>\n<html lang=\"%s\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex,nofollow\"><title>%s | alig.tech</title>"
            "<link rel=\"stylesheet\" href=\"/assets/base.css\"><link rel=\"stylesheet\" href=\"/assets/style.css\"></head><body>"
            "<header class=\"top\"><div class=\"wrap\"><a class=\"brand\" href=\"%s\"><img src=\"/assets/logo.svg\" width=\"176\" height=\"36\" alt=\"alig.tech\"></a></div></header>"
            "<main id=\"main\">%s</main></body></html>\n") % (d, escape(M[d]["baslik"]), "/en/" if d == "en" else "/", icerik)

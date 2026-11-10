"""Rapor HTML'i. Tum degerler html.escape ile yazilir; nesne adlari yalniz kanit listesinde gorunur."""
from html import escape

from tarama import kurallar

M = {
    "tr": {"baslik": "Sağlık taraması raporu", "ozet": "Özet", "tarama": "Tarama zamanı (UTC)", "motor": "Motor",
           "surum": "Maskeli", "evet": "evet", "hayir": "hayır", "bulgu": "Bulgular", "yok": "Bu taramada bulgu çıkmadı.",
           "kanit": "Kanıt", "neden": "Neden önemli", "oneri": "Öneri", "risk": "Önerinin riski", "geri": "Geri alma",
           "is": "İş büyüklüğü", "olcul": "Ölçülemeyenler", "olcul_a": "Bu denetimler çalışmadı. Sonuç temiz demek değildir.",
           "kapsam": "Bu tarama neye bakmaz",
           "kapsam_l": ["Yedekten geri dönüşün gerçekten çalıştığı", "İşletim sistemi ve ağ ayarları", "Uygulama sorguları ve yük altındaki davranış", "Veri içeriği"],
           "uyari": "Bu rapor tavsiye niteliğindedir. Hiçbir değişiklik uygulanmamıştır.",
           "sil": "Raporu şimdi sil", "bitis": "Rapor şu tarihte otomatik silinir (UTC)", "cta": "Denetim iste", "ana": "alig.tech",
           "onem": {"kritik": "Kritik", "yuksek": "Yüksek", "orta": "Orta", "dusuk": "Düşük", "bilgi": "Bilgi"},
           "isb": {"kucuk": "küçük", "orta": "orta", "buyuk": "büyük"},
           "nedenler": {"yetki": "yetki yok", "zaman_asimi": "zaman aşımı", "desteklenmiyor": "bu sürümde desteklenmiyor",
                        "yedek_sunucu": "yedek sunucuda çalışmaz", "hata": "hata", "calistirilmadi": "çalıştırılmadı"}},
    "en": {"baslik": "Health check report", "ozet": "Summary", "tarama": "Scan time (UTC)", "motor": "Engine",
           "surum": "Masked", "evet": "yes", "hayir": "no", "bulgu": "Findings", "yok": "No findings in this scan.",
           "kanit": "Evidence", "neden": "Why it matters", "oneri": "Proposal", "risk": "Risk of the proposal", "geri": "Rollback",
           "is": "Effort", "olcul": "Not measured", "olcul_a": "These checks did not run. This does not mean they are clean.",
           "kapsam": "What this scan does not look at",
           "kapsam_l": ["Whether a restore from backup really works", "Operating system and network settings", "Application queries and behaviour under load", "Data contents"],
           "uyari": "This report is advisory. No changes have been applied.",
           "sil": "Delete report now", "bitis": "Report is deleted automatically on (UTC)", "cta": "Request an audit", "ana": "alig.tech",
           "onem": {"kritik": "Critical", "yuksek": "High", "orta": "Medium", "dusuk": "Low", "bilgi": "Info"},
           "isb": {"kucuk": "small", "orta": "medium", "buyuk": "large"},
           "nedenler": {"yetki": "no permission", "zaman_asimi": "timeout", "desteklenmiyor": "not supported on this version",
                        "yedek_sunucu": "does not run on a standby", "hata": "error", "calistirilmadi": "not run"}},
}


def _kanit(kanit):
    out = []
    for k, v in kanit.items():
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        out.append("<li><code>%s</code>: %s</li>" % (escape(str(k)), escape(str(v))))
    return "<ul class=\"ev\">%s</ul>" % "".join(out)


def govde(rapor, dil, token, eylemler=True):
    m = M[dil if dil in M else "tr"]
    d = dil if dil in M else "tr"
    belge = rapor["belge"]
    bulgu, olcul = kurallar.degerlendir(belge)
    sayim = {o: sum(1 for b in bulgu if b["onem"] == o) for o in kurallar.ONEM}
    p = ["<article class=\"wrap prose report\">", "<h1>%s</h1>" % escape(m["baslik"]), "<p>%s</p>" % escape(m["uyari"]),
         "<h2>%s</h2>" % escape(m["ozet"]), "<dl class=\"facts\">",
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["tarama"]), escape(belge["olusturma_utc"])),
         "<dt>%s</dt><dd>PostgreSQL</dd>" % escape(m["motor"]),
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["surum"]), escape(m["evet"] if belge.get("maskeli") else m["hayir"])),
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["bulgu"]), escape(", ".join("%s: %d" % (m["onem"][o], n) for o, n in sayim.items() if n) or m["yok"])),
         "<dt>%s</dt><dd>%d</dd>" % (escape(m["olcul"]), len(olcul)), "</dl>", "<h2>%s</h2>" % escape(m["bulgu"])]
    for b in bulgu:
        p.append("<section class=\"finding-card sev-%s\"><h3>%s: %s</h3>" % (escape(b["onem"]), escape(m["onem"][b["onem"]]), escape(b["baslik"][d])))
        for anahtar, etiket in (("neden", "neden"), ("oneri", "oneri"), ("risk", "risk"), ("geri_alma", "geri")):
            p.append("<p><strong>%s.</strong> %s</p>" % (escape(m[etiket]), escape(b[anahtar][d])))
        p.append("<p><strong>%s.</strong> %s</p>" % (escape(m["is"]), escape(m["isb"][b["is"]])))
        p.append("<p><strong>%s.</strong></p>%s</section>" % (escape(m["kanit"]), _kanit(b["kanit"])))
    p.append("<h2>%s</h2><p>%s</p><ul>" % (escape(m["olcul"]), escape(m["olcul_a"])))
    for cid, neden in olcul:
        p.append("<li><code>%s</code>: %s</li>" % (escape(cid), escape(m["nedenler"].get(neden, neden))))
    p.append("</ul><h2>%s</h2><ul class=\"plain\">%s</ul>" % (escape(m["kapsam"]), "".join("<li>%s</li>" % escape(x) for x in m["kapsam_l"])))
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

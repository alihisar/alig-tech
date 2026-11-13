"""Rapor HTML'i. Tum degerler html.escape ile yazilir; nesne adlari yalniz kanit listesinde gorunur."""
from html import escape

from tarama import gecmis, kanit, katalog, kurallar, puan

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
                        "rol_bilinmiyor": "kısmen ölçüldü: tarama hesabının yetkileri okunamadı",
                        "replika_yok": "bu sunucudan beslenen replika yok",
                        "birincil_degil": "yedek sunucuda değerlendirilmez: birincil sunucuyu tarayın",
                        "sunucu_rolu_bilinmiyor": "kısmen ölçüldü: sunucunun birincil mi yedek mi olduğu okunamadı"},
           "rol": "Sunucu rolü", "rol_d": {True: "yedek sunucu: birincile özgü %d denetim uygulanmaz", False: "birincil", None: "bilinmiyor"},
           "sunucu": "Sunucu sürümü", "sinandi": "bu sürümde sınandı",
           "sinanmadi": "bu sürüm araçla henüz sınanmadı; kanıt güveni en çok orta gösterilir", "bilinmiyor_s": "bilinmiyor",
           "db": "Tablo, indeks ve sequence denetimleri",
           "db_d": "%d veritabanında çalıştı (sunucuda %d)",
           "db_a": "Atlanan veritabanları",
           "db_k": "Atlanan %d veritabanında tablo, indeks ve sequence durumu. Tarama hesabına bağlanma yetkisi verin ya da betiği --veritabanlari ile o veritabanları için çalıştırın.",
           "puan": "Sağlık puanı", "puan_yok": "hesaplanamadı: puana giren denetimlerin hiçbirinde kanıt yok",
           "kapsam_e": "Kanıt kapsamı", "kapsam_d": "%s (kanıtı olan denetim: %d / %d)", "yuzde": "%%%d",
           "puan_a": "Puan, uygulanabilir denetimlerin risk düzeyine göre ağırlıklı ortalamasıdır. Geçen denetim tam kredi alır, "
                     "uyarı veren denetim bulgunun önemine göre kısmi kredi alır, başarısız denetim kredi almaz. Kanıtı olmayan denetim "
                     "(Bilinmiyor, Alınamadı) da kredi almaz: eksik veri puanı yükseltmez. Uygulanmaz denetimler hesaba girmez. "
                     "Puanı kanıt kapsamıyla birlikte okuyun; puan yalnız bu raporun baktığı konuları anlatır.",
           "katsayi": "Ağırlıklar (denetimin risk düzeyine göre): %s. Uyarı kredisi (bulgunun önemine göre): %s.",
           "carpan": "Kategori çarpanları: %s.", "ozel": "Katsayılar bu kurulum için ayarlanmıştır.",
           "kategori_b": ("Kategori", "Puan", "Kanıt kapsamı", "Kanıtı olan denetim"), "kat_yok": "uygulanmaz",
           "kayip_h": "Puanı düşüren denetimler", "kayip_b": ("Kural", "Denetim", "Durum", "Puan kaybı"),
           "kayip_ozet": "Bulgulardan %s puan, kanıt eksikliğinden %s puan kayıp.",
           "tam": "Puanı düşüren denetim yok.", "puan_yok_k": "hesaplanamadı",
           "karsi": "Önceki taramayla karşılaştırma",
           "karsi_a": "Önceki tarama: %s. Aynı sunucu: küme kimliği ve rolü aynı. İki tarama da bugünkü kurallar ve katsayılarla değerlendirildi.",
           "karsi_katalog": "Önceki tarama toplayıcının eski sürümüyle yapıldı; o sürümde olmayan denetimler önceki taramada kanıtsız sayılır.",
           "karsi_b": ("Kural", "Denetim", "Değişim", "Önce", "Şimdi"),
           "karsi_d": {"NEW": "Yeni", "REGRESSED": "Kötüleşti", "PERSISTING": "Sürüyor", "RESOLVED": "Çözüldü", "UNKNOWN": "Bilinmiyor"},
           "karsi_n": {"kanit_kayboldu": "bu taramada kanıt yetersiz: çözüldü sayılmaz", "onceki_kanit_yok": "önceki taramada kanıt yoktu: yeni mi bilinmiyor"},
           "karsi_yok": "İki taramada da sorun çıkan denetim yok.",
           "gorunumler": {"yonetici": "Yönetici özeti", "teknik": "Teknik rapor"}, "gorunum_a": "Rapor görünümü",
           "yo_durum": "Genel durum", "yo_riskler": "En önemli riskler", "yo_isler": "Yapılması gerekenler (öncelik sırasıyla)",
           "yo_degisim": "Önceki taramaya göre değişim", "yo_dayanak": "Bu özet neye dayanır",
           "yo_d": {"kritik": "Acil dikkat gerekiyor: en az bir kritik bulgu var.",
                    "yuksek": "Dikkat gerekiyor: yüksek önemde bulgu var, kritik bulgu yok.",
                    "kucuk": "Küçük iyileştirmeler gerekiyor: yalnız orta, düşük ya da bilgi düzeyinde bulgu var.",
                    "temiz": "Bu taramada bulgu çıkmadı.",
                    "yok": "Genel durum belirlenemedi: puana giren denetimlerin hiçbirinde kanıt yok."},
           "yo_kanitsiz": "Ancak %d denetim için yeterli kanıt gelmedi; bu konular temiz sayılmadı.",
           "yo_risk_yok": "Listelenecek bulgu yok.",
           "yo_kismi": "Çıkan bir bulgu yok, ancak değerlendirme eksik: %d / %d denetim için kanıt geldi. Kanıtı gelmeyen konular temiz sayılmadı.",
           "yo_puan": "Sağlık puanı %s, kanıt kapsamı %s. Puan yalnız bu raporun baktığı konuları anlatır.",
           "yo_risk_b": ("Risk", "Önem", "Olası iş etkisi", "Kanıt türü"), "yo_daha": "Ve %d bulgu daha var; ayrıntısı teknik raporda.",
           "tur": {"HIGH": "Kesin kanıt: ayar ya da katalog durumu", "MEDIUM": "İstatistik ya da anlık görüntü",
                   "LOW": "Hipotez: dolaylı işaret, kesin sonuç değil"},
           "yo_is_yok": "Bu taramada öncelikli bir iş yok.",
           "yo_is_a": "Öneriler tavsiye niteliğindedir; hiçbir değişiklik uygulanmamıştır. Uygulamadan önce teknik raporun ön koşul ve doğrulama bölümüne bakın.",
           "yo_is_b": "iş büyüklüğü",
           "yo_onceki_yok": "Karşılaştırılacak önceki tarama bulunamadı (aynı firma ve aynı sunucu kimliğiyle daha önce yüklenmiş bir tarama gerekir).",
           "yo_onceki": "Önceki tarama: %s. Sağlık puanı: %s.",
           "yo_dayanak_a": "Bu özet, teknik raporun bulgularından kurallarla üretilir; yorum yazan bir model kullanılmaz. "
                           "Kanıt türü sütunu bulgunun ne kadar kesin olduğunu gösterir: hipotez olarak işaretli bulgu kesin sonuç değildir, doğrulanmalıdır.",
           "ayr": "Ölçüm ve yorum", "kanit_b": "Kanıt", "yorum_b": "Yorum", "tur_e": "Kanıt türü",
           "once_sonra": "Değişiklikten önce ve sonra",
           "once_sonra_l": ["Önerileri önce kendi ortamınızda ve bir bakım penceresinde sınayın; bu araç hiçbir değişiklik uygulamaz.",
                            "Değişiklikten önce yedek ve geri alma planı hazırlayın; her bulgunun geri alma notu yukarıdadır.",
                            "Değişiklikten sonra aynı taramayı yeniden çalıştırın; bulgunun kalktığını ve önceki taramayla karşılaştırmada Çözüldü olarak göründüğünü doğrulayın."]},
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
                        "rol_bilinmiyor": "partially measured: the scan account's privileges could not be read",
                        "replika_yok": "no replicas are fed by this server",
                        "birincil_degil": "not evaluated on a standby: scan the primary",
                        "sunucu_rolu_bilinmiyor": "partially measured: whether the server is a primary or a standby could not be read"},
           "rol": "Server role", "rol_d": {True: "standby: %d primary-only checks are not applicable", False: "primary", None: "unknown"},
           "sunucu": "Server version", "sinandi": "tested on this version",
           "sinanmadi": "this version has not been tested with the tool yet; evidence confidence is shown as medium at most", "bilinmiyor_s": "unknown",
           "db": "Table, index and sequence checks",
           "db_d": "ran in %d databases (%d on the server)",
           "db_a": "Skipped databases",
           "db_k": "Table, index and sequence state in the %d skipped databases. Grant the scan account permission to connect, or run the script with --veritabanlari for those databases.",
           "puan": "Health score", "puan_yok": "not calculated: none of the scored checks has evidence",
           "kapsam_e": "Evidence coverage", "kapsam_d": "%s (checks with evidence: %d of %d)", "yuzde": "%d%%",
           "puan_a": "The score is a weighted average of the applicable checks, weighted by each check's risk level. A passing check "
                     "earns full credit, a warning earns partial credit depending on the finding's severity, and a failing check earns "
                     "none. A check without evidence (Unknown, Unavailable) earns none either: missing data never raises the score. "
                     "Not applicable checks are left out. Read the score together with the evidence coverage; it only describes "
                     "what this report looks at.",
           "katsayi": "Weights (by the check's risk level): %s. Warning credit (by the finding's severity): %s.",
           "carpan": "Category multipliers: %s.", "ozel": "The coefficients have been adjusted for this installation.",
           "kategori_b": ("Category", "Score", "Evidence coverage", "Checks with evidence"), "kat_yok": "not applicable",
           "kayip_h": "Checks that lower the score", "kayip_b": ("Rule", "Check", "Status", "Points lost"),
           "kayip_ozet": "%s points lost to findings, %s points to missing evidence.",
           "tam": "No check lowers the score.", "puan_yok_k": "not calculated",
           "karsi": "Comparison with the previous scan",
           "karsi_a": "Previous scan: %s. Same server: same cluster identity and role. Both scans were evaluated with today's rules and coefficients.",
           "karsi_katalog": "The previous scan was made with an older version of the collector; checks it did not have count as having no evidence in that scan.",
           "karsi_b": ("Rule", "Check", "Change", "Before", "Now"),
           "karsi_d": {"NEW": "New", "REGRESSED": "Regressed", "PERSISTING": "Persisting", "RESOLVED": "Resolved", "UNKNOWN": "Unknown"},
           "karsi_n": {"kanit_kayboldu": "not enough evidence in this scan: not counted as resolved", "onceki_kanit_yok": "no evidence in the previous scan: unknown whether it is new"},
           "karsi_yok": "No check had a problem in either scan.",
           "gorunumler": {"yonetici": "Executive summary", "teknik": "Technical report"}, "gorunum_a": "Report view",
           "yo_durum": "Overall status", "yo_riskler": "Top risks", "yo_isler": "Actions in priority order",
           "yo_degisim": "Change since the previous scan", "yo_dayanak": "What this summary is based on",
           "yo_d": {"kritik": "Urgent attention needed: there is at least one critical finding.",
                    "yuksek": "Attention needed: there are high-severity findings and no critical finding.",
                    "kucuk": "Minor improvements needed: only medium, low or informational findings.",
                    "temiz": "No findings in this scan.",
                    "yok": "The overall status could not be determined: none of the scored checks has evidence."},
           "yo_kanitsiz": "However, %d checks did not return enough evidence; those topics are not counted as clean.",
           "yo_risk_yok": "There are no findings to list.",
           "yo_kismi": "There are no findings, but the assessment is incomplete: evidence came for %d of %d checks. Topics without evidence are not counted as clean.",
           "yo_puan": "Health score %s, evidence coverage %s. The score only describes what this report looks at.",
           "yo_risk_b": ("Risk", "Severity", "Possible business impact", "Evidence type"), "yo_daha": "And %d more findings; details are in the technical report.",
           "tur": {"HIGH": "Firm evidence: a setting or catalog state", "MEDIUM": "Statistics or a snapshot",
                   "LOW": "Hypothesis: an indirect sign, not a firm conclusion"},
           "yo_is_yok": "There is no priority work in this scan.",
           "yo_is_a": "The actions are advisory; no changes have been applied. Before acting, see the prerequisites and verification section of the technical report.",
           "yo_is_b": "effort",
           "yo_onceki_yok": "No previous scan to compare with was found (an earlier upload with the same firm and the same server identity is needed).",
           "yo_onceki": "Previous scan: %s. Health score: %s.",
           "yo_dayanak_a": "This summary is produced by rules from the findings of the technical report; no model writes commentary. "
                           "The evidence type column shows how firm a finding is: a finding marked as a hypothesis is not a firm conclusion and must be verified.",
           "ayr": "Measurement and interpretation", "kanit_b": "Evidence", "yorum_b": "Interpretation", "tur_e": "Evidence type",
           "once_sonra": "Before and after a change",
           "once_sonra_l": ["Test the proposals in your own environment and in a maintenance window first; this tool applies no changes.",
                            "Prepare a backup and a rollback plan before any change; each finding's rollback note is above.",
                            "After the change, run the same scan again; confirm the finding is gone and shows as Resolved in the comparison with the previous scan."]},
}


def _kanit(kanit, m):
    out = []
    for k, v in kanit.items():
        v = ", ".join(str(x) for x in v) if isinstance(v, list) else _deger(v, m)
        out.append("<li><code>%s</code>: %s</li>" % (escape(str(k)), escape(v)))
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


def _rol(s, motor, m):
    """PostgreSQL sunucusu birincil mi yedek mi; yedekte birincile ozgu kac denetimin uygulanmadigi."""
    if motor != "postgresql":
        return ""
    yedek = s.baglam.get("yedek")
    metin = m["rol_d"][yedek]
    if yedek:
        metin = metin % sum(1 for k in s.kayitlar if k["neden"] == "birincil_degil")
    return "<dt>%s</dt><dd>%s</dd>" % (escape(m["rol"]), escape(metin))


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


def _sayi(v, d, ondalik=None):
    """Turkcede ondalik ayirac virgul. ondalik verilirse o kadar basamak; 0'a yuvarlanan pozitif deger '<0,1' yazilir."""
    if ondalik is None:
        metin = "%g" % v
    elif 0 < v < 0.5 * 10 ** -ondalik:
        metin = "<%s" % ("%.*f" % (ondalik, 10 ** -ondalik))
    else:
        metin = "%.*f" % (ondalik, v)
    return metin.replace(".", ",") if d == "tr" else metin


def _puan(pn, sonuc, m, d):
    """Saglik puani bolumu: yontem, etkin katsayilar, kategori tablosu ve puani dusuren denetimler (tarama/puan.py)."""
    k = puan.ETKIN
    onem = lambda o: m["onem"][o].lower()  # noqa: E731
    yontem = m["katsayi"] % (", ".join("%s %s" % (onem(o), _sayi(v, d)) for o, v in k["agirlik"].items()),
                             ", ".join("%s %s" % (onem(o), _sayi(v, d)) for o, v in k["kredi_uyari"].items()))
    if not puan.varsayilan_mi():
        yontem += " " + m["carpan"] % ", ".join("%s %s" % (m["kategori"][c], _sayi(v, d)) for c, v in k["kategori_carpani"].items())
        yontem += " " + m["ozel"]
    satir = []
    for kat, x in pn.kategoriler.items():
        if not x["uygulanabilir"]:
            hucre = ("-", "-", m["kat_yok"])
        else:
            hucre = ("-" if x["puan"] is None else str(x["puan"]), m["yuzde"] % x["kapsam"], "%d / %d" % (x["olculen"], x["uygulanabilir"]))
        satir.append("<tr><th scope=\"row\">%s</th>%s</tr>" % (escape(m["kategori"][kat]), "".join(
            "<td data-label=\"%s\">%s</td>" % (escape(b), escape(h)) for b, h in zip(m["kategori_b"][1:], hucre))))
    p = ["<h2>%s</h2><p>%s</p><p>%s</p>" % (escape(m["puan"]), escape(m["puan_a"]), escape(yontem)),
         "<table class=\"tiers puanlar\"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
             "".join("<th scope=\"col\">%s</th>" % escape(b) for b in m["kategori_b"]), "".join(satir))]
    if pn.genel is None:
        return "\n".join(p)
    p.append("<h3>%s</h3>" % escape(m["kayip_h"]))
    if not pn.kayiplar:
        p.append("<p>%s</p>" % escape(m["tam"]))
        return "\n".join(p)
    ad = {r["kural"]: r["ad"][d] for r in sonuc.kayitlar}
    satir = []
    for x in pn.kayiplar:
        durum = m["durum"][x["durum"]] + (" (%s)" % m["nedenler"].get(x["neden"], x["neden"]) if x["tur"] == "kanit" and x["neden"] else "")
        hucre = (ad[x["kural"]], durum, _sayi(x["kayip"], d, 1))
        satir.append("<tr><th scope=\"row\"><code>%s</code></th>%s</tr>" % (escape(x["kural"]), "".join(
            "<td data-label=\"%s\">%s</td>" % (escape(b), escape(h)) for b, h in zip(m["kayip_b"][1:], hucre))))
    p.append("<p>%s</p>" % escape(m["kayip_ozet"] % (_sayi(pn.bulgu_kaybi, d, 1), _sayi(pn.kanit_kaybi, d, 1))))
    p.append("<table class=\"tiers durumlar kayiplar\"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
        "".join("<th scope=\"col\">%s</th>" % escape(b) for b in m["kayip_b"]), "".join(satir)))
    return "\n".join(p)


def _fark(a, b):
    f = b - a
    return "+%d" % f if f > 0 else ("\u2212%d" % -f if f < 0 else "0")


def _durum_metni(k, m):
    """Karsilastirma tablosundaki onceki ya da simdiki durum: Uyari (orta), Alinamadi (yetki yok)..."""
    if k["durum"] is None:
        return "-"
    ek = m["onem"][k["onem"]].lower() if k["onem"] else (m["nedenler"].get(k["neden"], k["neden"]) if k["neden"] else "")
    return m["durum"][k["durum"]] + (" (%s)" % ek if ek else "")


def _karsilastirma(c, m, d):
    """Onceki taramayla karsilastirma (tarama/gecmis.py): puan ve kapsam degisimi, kural kural degisim tablosu."""
    def puan_m(p):
        return m["puan_yok_k"] if p.genel is None else "%d/100" % p.genel
    op, yp = c.onceki_puan, c.yeni_puan
    puan_d = "%s → %s" % (puan_m(op), puan_m(yp)) + (" (%s)" % _fark(op.genel, yp.genel) if op.genel is not None and yp.genel is not None else "")
    kapsam_d = "%s → %s (%s)" % (m["yuzde"] % op.kapsam, m["yuzde"] % yp.kapsam, _fark(op.kapsam, yp.kapsam))
    p = ["<h2>%s</h2><p>%s</p>" % (escape(m["karsi"]), escape(m["karsi_a"] % c.onceki_tarih))]
    if c.katalog_farkli:
        p.append("<p>%s</p>" % escape(m["karsi_katalog"]))
    p.append("<dl class=\"facts\"><dt>%s</dt><dd>%s</dd><dt>%s</dt><dd>%s</dd></dl>" % (
        escape(m["puan"]), escape(puan_d), escape(m["kapsam_e"]), escape(kapsam_d)))
    if not c.kurallar:
        p.append("<p>%s</p>" % escape(m["karsi_yok"]))
        return "\n".join(p)
    p.append("<p>%s</p>" % escape(", ".join("%s: %d" % (m["karsi_d"][x], n) for x, n in c.say().items() if n)))
    satir = []
    for x in c.kurallar:
        degisim = m["karsi_d"][x["durum"]] + (": " + m["karsi_n"][x["neden"]] if x["neden"] else "")
        hucre = (x["ad"][d], degisim, _durum_metni(x["onceki"], m), _durum_metni(x["yeni"], m))
        satir.append("<tr><th scope=\"row\"><code>%s</code></th>%s</tr>" % (escape(x["kural"]), "".join(
            "<td data-label=\"%s\">%s</td>" % (escape(b), escape(h)) for b, h in zip(m["karsi_b"][1:], hucre))))
    p.append("<table class=\"tiers durumlar karsilastirma\"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
        "".join("<th scope=\"col\">%s</th>" % escape(b) for b in m["karsi_b"]), "".join(satir)))
    return "\n".join(p)


GORUNUMLER = ("yonetici", "teknik")   # ilki yonetici ozeti; varsayilan gorunum teknik rapordur (onceki davranis)


def gorunum_sec(deger):
    """Sorgu parametresinden gorunum: bilinmeyen ya da yanlis turdeki deger teknik rapora duser."""
    return deger if isinstance(deger, str) and deger in GORUNUMLER else "teknik"


def _sekme(secili, m):
    """Iki gorunum arasi baglantilar. Goreli sorgu baglantisi: sayfa nereden acildiysa (musteri ya da yonetim paneli) orada kalir."""
    ogeler = ["<a href=\"?gorunum=%s\"%s>%s</a>" % (g, " aria-current=\"page\"" if g == secili else "", escape(m["gorunumler"][g])) for g in GORUNUMLER]
    return "<nav class=\"rapor-sekme\" aria-label=\"%s\">%s</nav>" % (escape(m["gorunum_a"]), "".join(ogeler))


def _siralama(bulgu):
    return sorted(bulgu, key=lambda b: (kanit.ONEM_SIRASI.index(b["onem"]), b["kural"]))


def _yonetici(belge, sonuc, bulgu, pn, onceki, m, d):
    """Yonetici ozeti: yalniz kural ciktisindan, deterministik. Genel durum en agir bulguya gore; kanitsiz denetim temiz sayilmaz."""
    sirali = _siralama(bulgu)
    if pn.genel is None:
        durum = m["yo_d"]["yok"]
    else:
        agir = sirali[0]["onem"] if sirali else None
        eksik = pn.uygulanabilir - pn.olculen
        if agir is None and eksik:   # bulgu yok ama kanit eksik: "temiz" denmez
            durum = m["yo_kismi"] % (pn.olculen, pn.uygulanabilir)
        else:
            durum = m["yo_d"]["kritik" if agir == "kritik" else "yuksek" if agir == "yuksek" else "kucuk" if agir else "temiz"]
            if eksik:
                durum += " " + m["yo_kanitsiz"] % eksik
    p = ["<h2>%s</h2><p><strong>%s</strong></p>" % (escape(m["yo_durum"]), escape(durum))]
    if pn.genel is not None:
        p.append("<p>%s</p>" % escape(m["yo_puan"] % ("%d/100" % pn.genel, m["yuzde"] % pn.kapsam)))
    p.append("<h2>%s</h2>" % escape(m["yo_riskler"]))
    if sirali:
        satir = []
        for b in sirali[:5]:
            hucre = (m["onem"][b["onem"]], b["neden"][d], m["tur"][b["guven"]])
            satir.append("<tr><th scope=\"row\">%s</th>%s</tr>" % (escape(b["baslik"][d]), "".join(
                "<td data-label=\"%s\">%s</td>" % (escape(e), escape(h)) for e, h in zip(m["yo_risk_b"][1:], hucre))))
        p.append("<table class=\"tiers durumlar riskler\"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
            "".join("<th scope=\"col\">%s</th>" % escape(e) for e in m["yo_risk_b"]), "".join(satir)))
        if len(sirali) > 5:
            p.append("<p>%s</p>" % escape(m["yo_daha"] % (len(sirali) - 5)))
    else:
        p.append("<p>%s</p>" % escape(m["yo_risk_yok"]))
    p.append("<h2>%s</h2>" % escape(m["yo_isler"]))
    if sirali:
        p.append("<ol class=\"isler\">%s</ol>" % "".join(
            "<li><strong>%s.</strong> %s (%s: %s)</li>" % (escape(b["baslik"][d]), escape(b["oneri"][d]), escape(m["yo_is_b"]), escape(m["isb"][b["is"]]))
            for b in sirali))
        p.append("<p>%s</p>" % escape(m["yo_is_a"]))
    else:
        p.append("<p>%s</p>" % escape(m["yo_is_yok"]))
    p.append("<h2>%s</h2>" % escape(m["yo_degisim"]))
    if onceki:
        c = gecmis.karsilastir(onceki["belge"], belge)
        puan_m = lambda x: m["puan_yok_k"] if x.genel is None else "%d/100" % x.genel   # noqa: E731
        p.append("<p>%s</p>" % escape(m["yo_onceki"] % (c.onceki_tarih, "%s \u2192 %s" % (puan_m(c.onceki_puan), puan_m(c.yeni_puan)))))
        p.append("<p>%s</p>" % escape(", ".join("%s: %d" % (m["karsi_d"][x], n) for x, n in c.say().items() if n) or m["karsi_yok"]))
        if c.katalog_farkli:
            p.append("<p>%s</p>" % escape(m["karsi_katalog"]))
    else:
        p.append("<p>%s</p>" % escape(m["yo_onceki_yok"]))
    p.append("<h2>%s</h2><p>%s</p>" % (escape(m["yo_dayanak"]), escape(m["yo_dayanak_a"])))
    return "\n".join(p)


def _bulgu_karti(b, m, d):
    """Kanit blogu (olculen ve kaynak) ile yorum blogu (anlam, oneri, risk) ayri: yorum kanit gibi okunmasin."""
    kanit_blok = ["<div class=\"kanit-blok\"><h4>%s</h4>" % escape(m["kanit_b"]),
                  "<p><strong>%s.</strong> %s (%s). %s: %s. %s: %s (%s).</p>" % (
                      escape(m["kural"]), escape(b["kural"]), escape(m["kategori"][b["kategori"]]), escape(m["durum_e"]), escape(m["durum"][b["durum"]]),
                      escape(m["guven"]), escape(m["guven_d"][b["guven"]]), escape(m["tur"][b["guven"]])),
                  "<p><strong>%s.</strong> %s</p>" % (escape(m["kaynak"]), ", ".join("<code>%s</code>" % escape(x) for x in b["kaynak"])),
                  _kanit(b["kanit"], m), "</div>"]
    yorum = ["<div class=\"yorum-blok\"><h4>%s</h4>" % escape(m["yorum_b"])]
    for anahtar, etiket in (("neden", "neden"), ("oneri", "oneri"), ("risk", "risk"), ("geri_alma", "geri")):
        yorum.append("<p><strong>%s.</strong> %s</p>" % (escape(m[etiket]), escape(b[anahtar][d])))
    yorum.append("<p><strong>%s.</strong> %s</p></div>" % (escape(m["is"]), escape(m["isb"][b["is"]])))
    return ("<section class=\"finding-card sev-%s\"><h3>%s: %s</h3>" % (escape(b["onem"]), escape(m["onem"][b["onem"]]), escape(b["baslik"][d]))
            + "".join(kanit_blok) + "".join(yorum) + "</section>")


def govde(rapor, dil, token, eylemler=True, onceki=None, gorunum="teknik"):
    """onceki: karsilastirilacak onceki rapor (depo.onceki_rapor) ya da None. gorunum: GORUNUMLER (gecersiz deger teknik)."""
    d = dil if dil in M else "tr"
    m = M[d]
    gorunum = gorunum_sec(gorunum)
    belge = rapor["belge"]
    sonuc = kurallar.incele(belge)
    bulgu, olcul = sonuc.bulgular, sonuc.olculemeyen
    pn = puan.hesapla(sonuc)
    motor = belge.get("motor", "postgresql")
    p = ["<article class=\"wrap prose report\">", "<h1>%s</h1>" % escape(m["baslik"]), "<p>%s</p>" % escape(m["uyari"]),
         "<p><strong>%s</strong></p>" % escape(m["onsurum"]) if motor == "mssql" else "", _sekme(gorunum, m)]
    if gorunum == "yonetici":
        p += ["<dl class=\"facts\">",
              "<dt>%s</dt><dd>%s</dd>" % (escape(m["tarama"]), escape(belge["olusturma_utc"])),
              "<dt>%s</dt><dd>%s</dd>" % (escape(m["motor"]), escape(katalog.MOTOR_AD.get(motor, motor))), "</dl>",
              _yonetici(belge, sonuc, bulgu, pn, onceki, m, d)]
    else:
        p += _teknik(rapor, belge, sonuc, bulgu, pn, onceki, motor, m, d)
    p.append("<p>%s: %s</p>" % (escape(m["bitis"]), escape(rapor["bitis_utc"])))
    if not eylemler:
        p.append("</article>")
        return "\n".join(p), bulgu, olcul
    p.append("<form method=\"post\" action=\"/rapor/%s/sil\"><button class=\"btn btn-ghost\" type=\"submit\">%s</button></form>" % (escape(token), escape(m["sil"])))
    p.append("<p><a class=\"btn\" href=\"%s#iletisim\">%s</a></p></article>" % ("/en/" if d == "en" else "/", escape(m["cta"])))
    return "\n".join(p), bulgu, olcul


def _teknik(rapor, belge, sonuc, bulgu, pn, onceki, motor, m, d):
    """Teknik rapor: ozet bilgileri, puan, karsilastirma, bulgu kartlari (kanit ve yorum ayri), denetim tablosu, kapsam."""
    sayim = {o: sum(1 for b in bulgu if b["onem"] == o) for o in kurallar.ONEM}
    durum_sayim = sonuc.sayim()
    p = ["<h2>%s</h2>" % escape(m["ozet"]), "<dl class=\"facts\">",
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["tarama"]), escape(belge["olusturma_utc"])),
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["motor"]), escape(katalog.MOTOR_AD.get(motor, motor))),
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["surum"]), escape(m["evet"] if belge.get("maskeli") else m["hayir"])),
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["puan"]), escape(m["puan_yok"] if pn.genel is None else "%d/100" % pn.genel)),
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["kapsam_e"]), escape(m["kapsam_d"] % (m["yuzde"] % pn.kapsam, pn.olculen, pn.uygulanabilir))),
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["bulgu"]), escape(", ".join("%s: %d" % (m["onem"][o], n) for o, n in sayim.items() if n) or m["yok"])),
         "<dt>%s</dt><dd>%s</dd>" % (escape(m["denetimler"]), escape(", ".join("%s: %d" % (m["durum"][x], n) for x, n in durum_sayim.items() if n))),
         _surum(sonuc, motor, m), _rol(sonuc, motor, m), _kapsam(belge, m), "</dl>", _puan(pn, sonuc, m, d),
         _karsilastirma(gecmis.karsilastir(onceki["belge"], belge), m, d) if onceki else "", "<h2>%s</h2>" % escape(m["bulgu"]),
         "" if bulgu else "<p>%s</p>" % escape(m["yok"])]
    p += [_bulgu_karti(b, m, d) for b in bulgu]
    if bulgu:
        p.append("<h2>%s</h2><ul class=\"plain\">%s</ul>" % (escape(m["once_sonra"]), "".join("<li>%s</li>" % escape(x) for x in m["once_sonra_l"])))
    p.append(_durumlar(sonuc, m, d))
    kapsam_l = list(m["kapsam_l"])
    db = _db(belge)
    if db and db[2]:
        kapsam_l.insert(0, m["db_k"] % len(db[2]))
    p.append("<h2>%s</h2><ul class=\"plain\">%s</ul>" % (escape(m["kapsam"]), "".join("<li>%s</li>" % escape(x) for x in kapsam_l)))
    return p


def sayfa(rapor, dil, token, onceki=None, gorunum="teknik"):
    d = dil if dil in M else "tr"
    icerik, _, _ = govde(rapor, d, token, onceki=onceki, gorunum=gorunum)
    return ("<!doctype html>\n<html lang=\"%s\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex,nofollow\"><title>%s | alig.tech</title>"
            "<link rel=\"stylesheet\" href=\"/assets/base.css\"><link rel=\"stylesheet\" href=\"/assets/style.css\"></head><body>"
            "<header class=\"top\"><div class=\"wrap\"><a class=\"brand\" href=\"%s\"><img src=\"/assets/logo.svg\" width=\"176\" height=\"36\" alt=\"alig.tech\"></a></div></header>"
            "<main id=\"main\">%s</main></body></html>\n") % (d, escape(M[d]["baslik"]), "/en/" if d == "en" else "/", icerik)

"""SQL Server kurallari (ON SURUM: gercek sunucuda sinanmadi, kanit guveni en cok MEDIUM). Dil modeli yok.

Her kural kalici bir kimlikle (MS-SEC-001 gibi) kayitlidir ve PostgreSQL ile ayni kanit kaydini uretir (tarama/kanit.py).
Esikler: BELGE = Microsoft belgesinde yazili, MUHENDISLIK = kendi secimimiz (docs/doldurulacak.md'de listeli).
Nesne adlari baslik/aciklama metnine ya da gozleme girmez; yalniz kanit listesinde, kacisli olarak gosterilir.
"""
from datetime import datetime, timezone

from tarama import kanit

# Genisletilmis destegin son gunu (learn.microsoft.com/lifecycle). BELGE: tarihleri her yil dogrulayin.
# Anahtar: ProductMajorVersion (13 = SQL Server 2016, 14 = 2017, 15 = 2019, 16 = 2022, 17 = 2025).
MSSQL_EOL = {13: "2026-07-14", 14: "2027-10-12", 15: "2030-01-08", 16: "2033-01-11", 17: "2036-01-06"}
MSSQL_AD = {13: "2016", 14: "2017", 15: "2019", 16: "2022", 17: "2025"}

MUHENDISLIK = {
    "ms_yedek": "tam yedek: >168 saat yuksek; log yedegi (FULL/BULK_LOGGED): >24 saat yuksek",
    "ms_checkdb": "son basarili CHECKDB: >14 gun orta",
    "ms_acik_islem": "acik islem suresi: >=600 sn orta, >=3600 sn yuksek",
    "ms_sunucu_ayar": "cost threshold for parallelism = 5 (varsayilan): dusuk",
}


def _t(tr, en):
    return {"tr": tr, "en": en}


T = {
    "ms_surum_eol": dict(
        baslik=_t("SQL Server sürümü destek dışı ya da bitmek üzere", "SQL Server version is out of support or about to be"),
        neden=_t("Destek bitince güvenlik güncellemeleri yayımlanmaz.", "After end of support, security updates are no longer released."),
        oneri=_t("Desteklenen bir sürüme geçiş planlayın. Önce test ortamında, uyumluluk düzeyi ve geri dönüş adımlarıyla.", "Plan an upgrade to a supported version, first in a test environment with compatibility level checks and a rollback plan."),
        risk=_t("Orta. Sürüm geçişi bakım penceresi ister.", "Medium. A version upgrade needs a maintenance window."),
        geri=_t("Eski sunucu geçişten sonra da korunursa dönülebilir.", "Reversible while the old server is kept after the upgrade."), is_="buyuk"),
    "ms_yedek": dict(
        baslik=_t("Yedeği eksik ya da eski veritabanları var", "Databases with missing or old backups"),
        neden=_t("Yedek kaydı yoksa ya da eskiyse veri kaybı penceresi büyür. Yedek başka bir replikada alınıyorsa kayıt bu sunucuda görünmeyebilir.", "Without a recent backup the data-loss window grows. If backups run on another replica, the record may not appear on this server."),
        oneri=_t("Yedekleme işlerini ve geçmişini doğrulayın. Tam kurtarma modelindeki veritabanları için düzenli log yedeği alın ya da modeli gözden geçirin.", "Verify backup jobs and their history. For databases in full recovery, take regular log backups or review the recovery model."),
        risk=_t("Düşük. Yedekleme G/Ç yükü getirir.", "Low. Backups add I/O load."),
        geri=_t("Yedekleme işi durdurulabilir.", "A backup job can be stopped."), is_="orta"),
    "ms_checkdb": dict(
        baslik=_t("Bütünlük denetimi (CHECKDB) uzun süredir çalışmamış", "Integrity check (CHECKDB) has not run for a long time"),
        neden=_t("Sayfa bozulması fark edilmezse yedeklere de taşınır.", "Undetected page corruption is carried into backups as well."),
        oneri=_t("Düzenli DBCC CHECKDB planlayın. Büyük veritabanlarında yükü geri yüklenmiş bir kopyaya taşıyabilirsiniz.", "Schedule regular DBCC CHECKDB. For large databases you can move the load to a restored copy."),
        risk=_t("Orta. CHECKDB yoğun G/Ç ve tempdb kullanır.", "Medium. CHECKDB is heavy on I/O and tempdb."),
        geri=_t("Denetim veri değiştirmez, durdurulabilir.", "The check changes no data and can be stopped."), is_="orta"),
    "ms_db_durum": dict(
        baslik=_t("Çevrimiçi olmayan veritabanı var", "A database is not online"),
        neden=_t("Çevrimiçi olmayan veritabanına erişilemez; neden bozulma, eksik dosya ya da yarım kalmış geri yükleme olabilir.", "A database that is not online cannot be reached; the cause may be corruption, a missing file or an unfinished restore."),
        oneri=_t("Hata günlüğünü inceleyin ve durumun beklenen bir bakım olup olmadığını doğrulayın.", "Check the error log and confirm whether this state is expected maintenance."),
        risk=_t("Duruma bağlı.", "Depends on the cause."), geri=_t("Duruma bağlı.", "Depends on the cause."), is_="orta"),
    "ms_sayfa_dogrulama": dict(
        baslik=_t("Sayfa doğrulaması CHECKSUM değil", "Page verification is not CHECKSUM"),
        neden=_t("CHECKSUM olmadan disk kaynaklı sayfa bozulması geç fark edilir.", "Without CHECKSUM, page corruption caused by storage is detected late."),
        oneri=_t("PAGE_VERIFY seçeneğini CHECKSUM yapın. Sayfalar yeniden yazıldıkça korunur.", "Set PAGE_VERIFY to CHECKSUM. Pages are protected as they are rewritten."),
        risk=_t("Düşük.", "Low."), geri=_t("Seçenek eski değerine döndürülür.", "Set the option back to its previous value."), is_="kucuk"),
    "ms_auto": dict(
        baslik=_t("AUTO_SHRINK ya da AUTO_CLOSE açık", "AUTO_SHRINK or AUTO_CLOSE is on"),
        neden=_t("AUTO_SHRINK parçalanmaya ve gereksiz G/Ç yüküne, AUTO_CLOSE her bağlantıda açılış gecikmesine yol açar.", "AUTO_SHRINK causes fragmentation and needless I/O; AUTO_CLOSE adds a start-up delay on connections."),
        oneri=_t("İki seçeneği de kapatın.", "Turn both options off."),
        risk=_t("Düşük.", "Low."), geri=_t("Seçenek yeniden açılabilir.", "The option can be turned back on."), is_="kucuk"),
    "ms_trustworthy": dict(
        baslik=_t("TRUSTWORTHY açık veritabanı var", "A database has TRUSTWORTHY on"),
        neden=_t("TRUSTWORTHY, veritabanı sahibinin yetkileriyle sunucu düzeyinde yetki yükseltmeye imkân verebilir.", "TRUSTWORTHY can allow privilege escalation to server level through the database owner's rights."),
        oneri=_t("Gerekçesi yoksa kapatın. Gerekiyorsa sahibin düşük yetkili olduğunu doğrulayın.", "Turn it off unless there is a reason. If needed, confirm the owner has low privileges."),
        risk=_t("Orta. Bazı CLR ve veritabanları arası işlemler bu ayara dayanır.", "Medium. Some CLR and cross-database features depend on it."),
        geri=_t("Seçenek yeniden açılabilir.", "The option can be turned back on."), is_="kucuk"),
    "ms_tehlikeli_ayar": dict(
        baslik=_t("Saldırı yüzeyini büyüten sunucu ayarları açık", "Server settings that widen the attack surface are on"),
        neden=_t("xp_cmdshell, geçici dağıtık sorgular ve veritabanları arası sahiplik zinciri kötüye kullanıma açıktır.", "xp_cmdshell, ad hoc distributed queries and cross-database ownership chaining are open to abuse."),
        oneri=_t("Kullanılmayan ayarları kapatın. Kullanılıyorsa kimin, neden kullandığını belgeleyin.", "Turn off settings that are not used. If used, document who uses them and why."),
        risk=_t("Orta. Bu ayarlara dayanan işler bozulabilir.", "Medium. Jobs relying on these settings may break."),
        geri=_t("Ayar yeniden açılabilir.", "The setting can be turned back on."), is_="kucuk"),
    "ms_bellek": dict(
        baslik=_t("En yüksek sunucu belleği sınırlanmamış", "Max server memory is not limited"),
        neden=_t("Varsayılan değerde SQL Server belleğin tamamını kullanmaya çalışabilir ve işletim sistemini sıkıştırabilir.", "At the default value SQL Server may try to use all memory and starve the operating system."),
        oneri=_t("max server memory değerini, işletim sistemi ve diğer servislere pay bırakacak şekilde ayarlayın.", "Set max server memory so that the operating system and other services keep a share."),
        risk=_t("Düşük. Değer çok düşük seçilirse performans düşer.", "Low. Performance drops if the value is set too low."),
        geri=_t("Ayar eski değerine döndürülür, yeniden başlatma gerekmez.", "Set it back to the previous value; no restart needed."), is_="kucuk"),
    "ms_paralellik": dict(
        baslik=_t("Paralellik maliyet eşiği varsayılan değerde", "Cost threshold for parallelism is at the default"),
        neden=_t("Varsayılan 5 değeri küçük sorguların da paralel çalışmasına yol açabilir.", "The default of 5 can make small queries run in parallel as well."),
        oneri=_t("İş yükünüzü ölçerek daha yüksek bir değer deneyin.", "Measure your workload and try a higher value."),
        risk=_t("Düşük. Bazı sorgu planları değişir.", "Low. Some query plans change."),
        geri=_t("Ayar eski değerine döndürülür.", "Set it back to the previous value."), is_="kucuk"),
    "ms_sa": dict(
        baslik=_t("sa girişi etkin", "The sa login is enabled"),
        neden=_t("sa, adı bilinen ve en yüksek yetkili giriştir; parola deneme saldırılarının ilk hedefidir.", "sa is a well-known login with the highest privileges and the first target of password guessing."),
        oneri=_t("sa girişini devre dışı bırakın, yönetim için kişiye bağlı girişler kullanın.", "Disable the sa login and use named logins for administration."),
        risk=_t("Orta. sa ile bağlanan eski uygulama ya da işler bozulur.", "Medium. Old applications or jobs that connect as sa will break."),
        geri=_t("Giriş yeniden etkinleştirilebilir.", "The login can be enabled again."), is_="kucuk"),
    "ms_sysadmin": dict(
        baslik=_t("sysadmin rolünün üyeleri", "Members of the sysadmin role"),
        neden=_t("sysadmin üyeleri sunucuda her şeyi yapabilir. Liste düzenli gözden geçirilmelidir.", "sysadmin members can do anything on the server. The list should be reviewed regularly."),
        oneri=_t("Her üyenin hâlâ gerekli olduğunu doğrulayın, gerekmeyenleri çıkarın.", "Confirm each member is still needed and remove those that are not."),
        risk=_t("Orta. Yetkisi alınan hesabın işleri bozulabilir.", "Medium. Jobs of an account that loses the role may break."),
        geri=_t("Üyelik yeniden verilebilir.", "Membership can be granted again."), is_="kucuk"),
    "ms_parola_politikasi": dict(
        baslik=_t("Parola politikası uygulanmayan SQL girişleri var", "SQL logins without password policy enforcement"),
        neden=_t("Politika denetimi kapalı girişlerde zayıf parola ve kilitlenme koruması yoktur.", "Logins with the policy check off have no weak-password or lockout protection."),
        oneri=_t("Bu girişlerde CHECK_POLICY seçeneğini açın.", "Turn CHECK_POLICY on for these logins."),
        risk=_t("Düşük. Zayıf parolalı hesaplar parola değiştirmek zorunda kalabilir.", "Low. Accounts with weak passwords may have to change them."),
        geri=_t("Seçenek kapatılabilir.", "The option can be turned off."), is_="kucuk"),
    "ms_tempdb": dict(
        baslik=_t("tempdb tek veri dosyasıyla çalışıyor", "tempdb runs with a single data file"),
        neden=_t("Çok çekirdekli sunucuda tek dosya, ayırma sayfalarında çekişmeye yol açabilir.", "On a multi-core server a single file can cause contention on allocation pages."),
        oneri=_t("Eşit boyutlu birden çok veri dosyası ekleyin (çekirdek sayısı kadar, en çok 8 ile başlayın).", "Add several equally sized data files (one per core, starting with at most 8)."),
        risk=_t("Düşük.", "Low."), geri=_t("Eklenen dosyalar boşaltılıp kaldırılabilir.", "Added files can be emptied and removed."), is_="kucuk"),
    "ms_ag": dict(
        baslik=_t("Always On replikası sağlıklı değil", "An Always On replica is not healthy"),
        neden=_t("Eşitlenmeyen ya da bağlı olmayan replika, yük devrinde veri kaybına ya da kesintiye yol açar.", "A replica that is not synchronised or not connected leads to data loss or downtime on failover."),
        oneri=_t("Replika bağlantısını, eşitleme durumunu ve gönderim/yineleme kuyruklarını inceleyin.", "Check the replica connection, synchronisation state and the send and redo queues."),
        risk=_t("Duruma bağlı.", "Depends on the cause."), geri=_t("Duruma bağlı.", "Depends on the cause."), is_="orta"),
    "ms_dosya_buyume": dict(
        baslik=_t("Yüzde ile büyüyen dosyalar var", "Files that grow by percentage"),
        neden=_t("Yüzdeli büyüme dosya büyüdükçe daha uzun süren ve öngörülemeyen büyüme adımlarına yol açar.", "Percentage growth makes growth steps longer and less predictable as the file gets larger."),
        oneri=_t("Büyümeyi sabit bir boyuta çevirin ve dosyaları beklenen boyuta önceden büyütün.", "Switch to a fixed growth size and pre-size files to the expected size."),
        risk=_t("Düşük.", "Low."), geri=_t("Ayar eski değerine döndürülür.", "Set it back to the previous value."), is_="kucuk"),
    "ms_sifreleme": dict(
        baslik=_t("Şifrelenmemiş ağ bağlantıları var", "Unencrypted network connections exist"),
        neden=_t("Şifrelenmemiş bağlantıda veri ve kimlik bilgileri ağda okunabilir.", "On an unencrypted connection, data and credentials can be read on the network."),
        oneri=_t("Sunucuya geçerli bir sertifika yükleyin ve şifrelemeyi zorunlu kılın; önce istemcilerin uyumunu doğrulayın.", "Install a valid certificate on the server and force encryption; confirm client compatibility first."),
        risk=_t("Orta. Eski istemciler bağlanamayabilir, servis yeniden başlatılır.", "Medium. Old clients may fail to connect and the service restarts."),
        geri=_t("Zorunlu şifreleme kapatılabilir.", "Forced encryption can be turned off."), is_="orta"),
    "ms_acik_islem": dict(
        baslik=_t("Uzun süredir açık işlemler var", "Long-running open transactions"),
        neden=_t("Açık işlem log dosyasının kesilmesini engeller ve kilit tutar.", "An open transaction prevents log truncation and holds locks."),
        oneri=_t("Oturumun sahibini bulun; uygulamadaki işlem sınırlarını gözden geçirin.", "Find the owner of the session and review transaction boundaries in the application."),
        risk=_t("Orta. Oturumu sonlandırmak işlemi geri alır.", "Medium. Ending the session rolls the transaction back."),
        geri=_t("Uygulanmaz.", "Not applicable."), is_="kucuk"),
    "ms_kimlik": dict(
        baslik=_t("Karma kimlik doğrulama açık", "Mixed authentication mode is on"),
        neden=_t("SQL girişleri merkezi parola politikası ve çok adımlı doğrulamanın dışında kalır.", "SQL logins stay outside central password policy and multi-factor authentication."),
        oneri=_t("Mümkünse yalnızca Windows kimlik doğrulamasına geçin; SQL girişlerini azaltın.", "Where possible move to Windows authentication only and reduce SQL logins."),
        risk=_t("Orta. SQL girişi kullanan uygulamalar etkilenir, servis yeniden başlatılır.", "Medium. Applications using SQL logins are affected and the service restarts."),
        geri=_t("Kip eski değerine döndürülür.", "Set the mode back to its previous value."), is_="orta"),
    "ms_sysadmin_ile_tarama": dict(
        baslik=_t("Tarama sysadmin üyesi bir girişle çalıştırılmış", "The scan was run with a sysadmin login"),
        neden=_t("Tarama için gereken yetki yalnızca VIEW SERVER STATE ve VIEW ANY DEFINITION'dır.", "The scan only needs VIEW SERVER STATE and VIEW ANY DEFINITION."),
        oneri=_t("Sonraki taramayı ayrı, düşük yetkili bir girişle çalıştırın.", "Run the next scan with a separate low-privilege login."),
        risk=_t("Yok.", "None."), geri=_t("Uygulanmaz.", "Not applicable."), is_="kucuk"),
}


def _f(kontrol, sablon, onem, kanit_):
    t = T[sablon]
    return {"kontrol": kontrol, "sablon": sablon, "onem": onem, "baslik": t["baslik"], "neden": t["neden"],
            "oneri": t["oneri"], "risk": t["risk"], "geri_alma": t["geri"], "is": t["is_"], "kanit": kanit_}


# Kolon turleri. Yuklemede SQL Server icin tur denetlenmez (gercek sunucu ciktisi sinanmadi); kural motoru turu
# uymayan satiri degerlendirmeye almaz ve sonucu kismi sayar (tarama/kanit.py).
_M, _T = "metin", "tamsayi"
TURLER = {
    "ms_surum": {"ana_surum": _T, "surum": _M, "motor_turu": _T},
    "ms_yedek": {"veritabani": _M, "kurtarma_modeli": _M, "tam_saat": _T, "log_saat": _T},
    "ms_checkdb": {"veritabani": _M, "gun": _T},
    "ms_db_ayar": {"veritabani": _M, "kimlik": _T, "auto_shrink": _T, "auto_close": _T, "sayfa_dogrulama": _M, "durum": _M, "trustworthy": _T},
    "ms_sunucu_ayar": {"ad": _M, "deger": _T},
    "ms_sa": {"devre_disi": _T, "adi_sa": _T},
    "ms_sysadmin": {"giris": _M, "tur": _M, "devre_disi": _T},
    "ms_parola_politikasi": {"sayi": _T},
    "ms_tempdb": {"veri_dosyasi": _T, "cpu": _T},
    "ms_ag": {"grup": _M, "replika": _M, "saglik": _M, "rol": _M, "baglanti": _M},
    "ms_dosya_buyume": {"veritabani": _M, "dosya": _M, "tur": _M},
    "ms_sifreleme": {"toplam": _T, "sifreli": _T},
    "ms_acik_islem": {"giris": _M, "sure_sn": _T},
    "ms_kimlik": {"yalniz_windows": _T},
}

KURALLAR = []
kural = kanit.kayitci(KURALLAR, "mssql")
K = kanit.Kaynak
BILGI = ()
TEHLIKELI_AYARLAR = ("xp_cmdshell", "Ad Hoc Distributed Queries", "cross db ownership chaining")


def _ayar(r, ad):
    """sys.configurations degeri; satir yoksa ya da deger bos ise Belirsiz."""
    for x in r:
        if x["ad"] == ad and x.get("deger") is not None:
            return x["deger"]
    raise kanit.Belirsiz("eksik_veri")


# Kural sirasi bulgularin ayni onemdeki sirasidir; kimlikler kalicidir, yeni kural yeni numara alir.

@kural("MS-MAINT-001", "bakim", "HIGH", [K("ms_surum", "tek", ("ana_surum", "motor_turu"))],
       _t("Sürüm desteği", "Version support"),
       _t("Genişletilmiş destek en az 90 gün daha sürüyor.", "Extended support lasts at least 90 more days."))
def _surum(r, g):
    s = r[0]
    if s["motor_turu"] in (5, 8):   # Azure SQL Database ve Managed Instance: surum yonetilen hizmette
        raise kanit.Uygulanmaz("yonetilen_hizmet")
    ana = s["ana_surum"]
    ad = MSSQL_AD.get(ana, str(ana))
    g.gozle(surum=ad)
    eol = MSSQL_EOL.get(ana)
    if eol is None and ana < min(MSSQL_EOL):
        return [_f("ms_surum", "ms_surum_eol", "yuksek", {"surum": ad, "destek_sonu": "gecmis"})]
    if eol:
        gun = (datetime.strptime(eol, "%Y-%m-%d").replace(tzinfo=timezone.utc) - g.taranan).days
        if gun < 0:
            return [_f("ms_surum", "ms_surum_eol", "yuksek", {"surum": ad, "destek_sonu": eol})]
        if gun <= 90:
            return [_f("ms_surum", "ms_surum_eol", "orta", {"surum": ad, "destek_sonu": eol, "kalan_gun": gun})]
    return []


@kural("MS-BACKUP-001", "yedek", "MEDIUM", [K("ms_yedek", "en_az_bir", ("kurtarma_modeli",))],
       _t("Yedek geçmişi", "Backup history"),
       _t("Bu sunucunun msdb kaydına göre her veritabanının son 7 günde tam yedeği, tam ya da toplu kayıtlı kurtarma "
          "modelindekilerin son 24 saatte log yedeği var.",
          "According to msdb on this server, every database has a full backup in the last 7 days, and those in full or "
          "bulk-logged recovery a log backup in the last 24 hours."))
def _yedek(r, g):
    tam = [x for x in r if x.get("tam_saat") is None or x["tam_saat"] > 168]
    log = [x for x in r if x["kurtarma_modeli"] in ("FULL", "BULK_LOGGED") and (x.get("log_saat") is None or x["log_saat"] > 24)]
    if not (tam or log):
        return []
    return [_f("ms_yedek", "ms_yedek", "yuksek",
               {"tam_yedegi_eksik_ya_da_eski": len(tam), "log_yedegi_eksik_ya_da_eski": len(log),
                "nesneler": sorted({str(x.get("veritabani")) for x in tam + log})[:10],
                "esik_tam_saat": 168, "esik_log_saat": 24})]


@kural("MS-MAINT-002", "bakim", "HIGH", [K("ms_checkdb", "en_az_bir", ("gun",))],
       _t("Bütünlük denetimi (CHECKDB)", "Integrity check (CHECKDB)"),
       _t("Her veritabanında son başarılı CHECKDB 14 günden yeni.", "In every database the last successful CHECKDB is less than 14 days old."))
def _checkdb(r, g):
    eski = [x for x in r if x["gun"] > 14]
    if not eski:
        return []
    return [_f("ms_checkdb", "ms_checkdb", "orta",
               {"veritabani_sayisi": len(eski), "hic_calismamis": sum(1 for x in eski if x["gun"] > 36500),
                "nesneler": [str(x.get("veritabani")) for x in eski[:10]], "esik_gun": 14})]


@kural("MS-HA-001", "ha_dr", "HIGH", [K("ms_db_ayar", "en_az_bir", ("durum",))],
       _t("Veritabanı durumu", "Database state"),
       _t("Bütün veritabanları ONLINE.", "All databases are ONLINE."))
def _db_durum(r, g):
    kapali = [x for x in r if x["durum"] != "ONLINE"]
    if not kapali:
        return []
    return [_f("ms_db_ayar", "ms_db_durum", "yuksek",
               {"veritabani_sayisi": len(kapali), "nesneler": [str(x.get("veritabani")) for x in kapali[:10]],
                "durumlar": sorted({str(x["durum"]) for x in kapali})})]


@kural("MS-CONFIG-001", "konfigurasyon", "HIGH", [K("ms_db_ayar", "en_az_bir", ("sayfa_dogrulama",))],
       _t("Sayfa doğrulama", "Page verification"),
       _t("Bütün veritabanlarında PAGE_VERIFY CHECKSUM.", "PAGE_VERIFY is CHECKSUM in all databases."))
def _sayfa_dogrulama(r, g):
    dogrulama = [x for x in r if x["sayfa_dogrulama"] != "CHECKSUM"]
    if not dogrulama:
        return []
    return [_f("ms_db_ayar", "ms_sayfa_dogrulama", "yuksek",
               {"veritabani_sayisi": len(dogrulama), "nesneler": [str(x.get("veritabani")) for x in dogrulama[:10]]})]


@kural("MS-CONFIG-002", "konfigurasyon", "HIGH", [K("ms_db_ayar", "en_az_bir")],
       _t("AUTO_SHRINK ve AUTO_CLOSE", "AUTO_SHRINK and AUTO_CLOSE"),
       _t("Hiçbir veritabanında AUTO_SHRINK ya da AUTO_CLOSE açık değil.", "No database has AUTO_SHRINK or AUTO_CLOSE on."))
def _auto(r, g):
    oto = [x for x in r if x.get("auto_shrink") == 1 or x.get("auto_close") == 1]
    if any(x.get("auto_shrink") not in (0, 1) or x.get("auto_close") not in (0, 1) for x in r if x not in oto):
        g.kismi("eksik_veri")
    if not oto:
        return []
    return [_f("ms_db_ayar", "ms_auto", "orta",
               {"auto_shrink": sum(1 for x in oto if x.get("auto_shrink") == 1),
                "auto_close": sum(1 for x in oto if x.get("auto_close") == 1),
                "nesneler": [str(x.get("veritabani")) for x in oto[:10]]})]


@kural("MS-SEC-001", "guvenlik", "HIGH", [K("ms_db_ayar", "en_az_bir", ("trustworthy",))],
       _t("TRUSTWORTHY", "TRUSTWORTHY"),
       _t("msdb dışında TRUSTWORTHY açık veritabanı yok.", "No database other than msdb has TRUSTWORTHY on."))
def _trustworthy(r, g):
    guven = [x for x in r if x["trustworthy"] == 1 and x.get("kimlik") != 4]  # msdb varsayilan olarak aciktir
    if not guven:
        return []
    return [_f("ms_db_ayar", "ms_trustworthy", "orta",
               {"veritabani_sayisi": len(guven), "nesneler": [str(x.get("veritabani")) for x in guven[:10]]})]


@kural("MS-SEC-002", "guvenlik", "HIGH", [K("ms_sunucu_ayar", "en_az_bir", ("ad",))],
       _t("Saldırı yüzeyini büyüten ayarlar", "Settings that widen the attack surface"),
       _t("xp_cmdshell, Ad Hoc Distributed Queries ve cross db ownership chaining kapalı.",
          "xp_cmdshell, Ad Hoc Distributed Queries and cross db ownership chaining are off."))
def _tehlikeli_ayar(r, g):
    deger = {x["ad"]: x.get("deger") for x in r}
    g.gozle({a: deger.get(a) for a in TEHLIKELI_AYARLAR})
    acik = [a for a in TEHLIKELI_AYARLAR if deger.get(a) == 1]
    if acik:
        return [_f("ms_sunucu_ayar", "ms_tehlikeli_ayar", "yuksek" if "xp_cmdshell" in acik else "orta", {"acik_ayarlar": acik})]
    if any(deger.get(a) != 0 for a in TEHLIKELI_AYARLAR):
        raise kanit.Belirsiz("eksik_veri")
    return []


@kural("MS-CONFIG-003", "konfigurasyon", "HIGH", [K("ms_sunucu_ayar", "en_az_bir", ("ad",))],
       _t("En yüksek sunucu belleği", "Max server memory"),
       _t("max server memory varsayılan (sınırsız) değerde değil.", "max server memory is not at the default (unlimited) value."))
def _bellek(r, g):
    v = _ayar(r, "max server memory (MB)")
    g.gozle(max_server_memory_mb=v)
    if v == 2147483647:
        return [_f("ms_sunucu_ayar", "ms_bellek", "orta", {"max_server_memory_mb": 2147483647, "anlami": "varsayilan, sinirsiz"})]
    return []


@kural("MS-PERF-001", "performans", "HIGH", [K("ms_sunucu_ayar", "en_az_bir", ("ad",))],
       _t("Paralellik maliyet eşiği", "Cost threshold for parallelism"),
       _t("cost threshold for parallelism varsayılan 5 değerinde değil.", "cost threshold for parallelism is not at the default of 5."))
def _paralellik(r, g):
    v = _ayar(r, "cost threshold for parallelism")
    g.gozle(cost_threshold_for_parallelism=v)
    if v == 5:
        return [_f("ms_sunucu_ayar", "ms_paralellik", "dusuk", {"cost_threshold_for_parallelism": 5})]
    return []


@kural("MS-SEC-003", "guvenlik", "HIGH", [K("ms_sa", "tek", ("devre_disi",))],
       _t("sa girişi", "The sa login"),
       _t("sa girişi devre dışı.", "The sa login is disabled."))
def _sa(r, g):
    s = r[0]
    if s["devre_disi"] not in (0, 1):
        raise kanit.Belirsiz("gecersiz_veri")
    g.gozle(sa_devre_disi=s["devre_disi"] == 1)
    if s["devre_disi"] == 0:
        return [_f("ms_sa", "ms_sa", "orta", {"etkin": True, "adi_degistirilmis": s.get("adi_sa") == 0})]
    return []


@kural("MS-SEC-004", "guvenlik", "HIGH", [K("ms_sysadmin", "en_az_bir", ("devre_disi",))],
       _t("sysadmin üyeleri", "sysadmin members"),
       _t("sysadmin rolünün etkin üyesi yok; varsa liste gözden geçirilir.", "The sysadmin role has no enabled members; if it has, the list is reviewed."))
def _sysadmin(r, g):
    etkin = [x for x in r if x["devre_disi"] != 1]
    g.gozle(etkin_uye=len(etkin))
    if not etkin:
        return []
    return [_f("ms_sysadmin", "ms_sysadmin", "bilgi", {"uye_sayisi": len(etkin), "nesneler": [str(x.get("giris")) for x in etkin[:20]]})]


@kural("MS-SEC-005", "guvenlik", "HIGH", [K("ms_parola_politikasi", "tek", ("sayi",))],
       _t("Parola politikası", "Password policy"),
       _t("Etkin SQL girişlerinin hepsinde CHECK_POLICY açık.", "CHECK_POLICY is on for every enabled SQL login."))
def _parola_politikasi(r, g):
    sayi = r[0]["sayi"]
    if sayi < 0:
        raise kanit.Belirsiz("gecersiz_veri")
    g.gozle(politikasiz_giris=sayi)
    if sayi > 0:
        return [_f("ms_parola_politikasi", "ms_parola_politikasi", "orta", {"giris_sayisi": sayi})]
    return []


@kural("MS-PERF-002", "performans", "HIGH", [K("ms_tempdb", "tek", ("veri_dosyasi", "cpu"))],
       _t("tempdb veri dosyaları", "tempdb data files"),
       _t("Çok çekirdekli sunucuda tempdb birden çok veri dosyasıyla çalışıyor.", "On a multi-core server tempdb has more than one data file."))
def _tempdb(r, g):
    dosya, cpu = r[0]["veri_dosyasi"], r[0]["cpu"]
    if dosya < 1 or cpu < 1:
        raise kanit.Belirsiz("gecersiz_veri")
    g.gozle(veri_dosyasi=dosya, cpu=cpu)
    if dosya == 1 and cpu > 1:
        return [_f("ms_tempdb", "ms_tempdb", "orta", {"veri_dosyasi": 1, "cpu": cpu})]
    return []


@kural("MS-HA-002", "ha_dr", "HIGH", [K("ms_ag")],
       _t("Always On replikaları", "Always On replicas"),
       _t("Bütün replikalar HEALTHY ve CONNECTED.", "All replicas are HEALTHY and CONNECTED."))
def _ag(r, g):
    if not r:
        raise kanit.Uygulanmaz("ag_yok")
    kotu = [x for x in r if x.get("saglik") not in (None, "HEALTHY") or x.get("baglanti") not in (None, "CONNECTED")]
    if any(x.get("saglik") is None or x.get("baglanti") is None for x in r if x not in kotu):
        g.kismi("eksik_veri")
    g.gozle(replika=len(r))
    if not kotu:
        return []
    return [_f("ms_ag", "ms_ag", "yuksek",
               {"replika_sayisi": len(kotu), "nesneler": ["%s / %s" % (x.get("grup"), x.get("replika")) for x in kotu[:10]],
                "durumlar": sorted({"%s, %s" % (x.get("saglik"), x.get("baglanti")) for x in kotu})})]


@kural("MS-CONFIG-004", "konfigurasyon", "HIGH", [K("ms_dosya_buyume")],
       _t("Dosya büyüme ayarı", "File growth setting"),
       _t("Yüzde ile büyüyen veri ya da log dosyası yok.", "No data or log file grows by percentage."))
def _dosya_buyume(r, g):
    if not r:
        return []
    return [_f("ms_dosya_buyume", "ms_dosya_buyume", "dusuk",
               {"dosya_sayisi": len(r), "nesneler": ["%s / %s" % (x.get("veritabani"), x.get("dosya")) for x in r[:10]]})]


@kural("MS-SEC-006", "guvenlik", "MEDIUM", [K("ms_sifreleme", "tek", ("toplam", "sifreli"))],
       _t("Bağlantı şifrelemesi", "Connection encryption"),
       _t("Tarama anındaki TCP bağlantılarının hepsi şifreli.", "All TCP connections at scan time are encrypted."))
def _sifreleme(r, g):
    toplam, sifreli = r[0]["toplam"], r[0]["sifreli"]
    if toplam < 0 or sifreli < 0 or sifreli > toplam:
        raise kanit.Belirsiz("gecersiz_veri")
    g.gozle(tcp_baglanti=toplam, sifreli=sifreli)
    if toplam == 0:
        raise kanit.Uygulanmaz("tcp_baglanti_yok")
    if toplam > sifreli:
        return [_f("ms_sifreleme", "ms_sifreleme", "orta", {"tcp_baglanti": toplam, "sifreli": sifreli, "sifresiz": toplam - sifreli})]
    return []


@kural("MS-PERF-003", "performans", "MEDIUM", [K("ms_acik_islem", "herhangi", ("sure_sn",))],
       _t("Uzun açık işlemler", "Long open transactions"),
       _t("Tarama anında 10 dakikadan uzun süredir açık kullanıcı işlemi yok.", "At scan time no user transaction has been open for more than 10 minutes."))
def _acik_islem(r, g):
    uzun = [x for x in r if x["sure_sn"] >= 600]
    if not uzun:
        return []
    en = max(x["sure_sn"] for x in uzun)
    return [_f("ms_acik_islem", "ms_acik_islem", "yuksek" if en >= 3600 else "orta",
               {"oturum_sayisi": len(uzun), "en_uzun_sn": en, "esik_orta_sn": 600, "esik_yuksek_sn": 3600})]


@kural("MS-SEC-007", "guvenlik", "HIGH", [K("ms_kimlik", "tek", ("yalniz_windows",))],
       _t("Kimlik doğrulama kipi", "Authentication mode"),
       _t("Yalnızca Windows kimlik doğrulaması açık.", "Only Windows authentication is enabled."))
def _kimlik(r, g):
    v = r[0]["yalniz_windows"]
    if v not in (0, 1):
        raise kanit.Belirsiz("gecersiz_veri")
    g.gozle(yalniz_windows=v == 1)
    if v == 0:
        return [_f("ms_kimlik", "ms_kimlik", "dusuk", {"yalniz_windows": False})]
    return []


@kural("MS-SEC-008", "guvenlik", "HIGH", [K(kanit.TOPLAYICI, "tek", ("superuser",))],
       _t("Taramanın hesabı", "Scan account"),
       _t("Tarama sysadmin üyesi olmayan bir girişle çalıştırıldı.", "The scan ran with a login that is not a sysadmin member."),
       kaynak=("IS_SRVROLEMEMBER('sysadmin')",))
def _tarama_hesabi(r, g):
    g.gozle(sysadmin=r[0]["superuser"])
    if r[0]["superuser"] is True:
        return [_f(kanit.TOPLAYICI, "ms_sysadmin_ile_tarama", "orta", {"sysadmin": True})]
    return []

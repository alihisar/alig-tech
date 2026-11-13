"""PostgreSQL kurallari. Dil modeli yok: ayni girdi her zaman ayni bulgulari ve durumlari verir.

Her kural kalici bir kimlikle (PG-SEC-001 gibi) kayitlidir ve her taramada tek bir kanit kaydi uretir: durum, onem,
guven, kaynak (tarama/kanit.py). Kural listesi ve gecme kosullari: docs/kural-katalogu.md (uretilir).
Esikler: BELGE = resmi belgede/politikada yazili deger, MUHENDISLIK = kendi secimimiz (docs/doldurulacak.md'de listeli).
Nesne adlari asla baslik/aciklama metnine ya da gozleme girmez; yalniz kanit listesinde, kacisli olarak gosterilir.
"""
from datetime import datetime, timezone

from tarama import kanit, katalog, yukleme

ONEM = ("kritik", "yuksek", "orta", "dusuk", "bilgi")
IS = ("kucuk", "orta", "buyuk")

# PostgreSQL surum politikasi (postgresql.org/support/versioning) EOL tarihleri. BELGE: tarihleri her yil dogrulayin.
PG_EOL = {13: "2025-11-13", 14: "2026-11-12", 15: "2027-11-11", 16: "2028-11-09", 17: "2029-11-08", 18: "2030-11-14"}

# Resmi belgede olmayan esikler (MUHENDISLIK)
MUHENDISLIK = {
    "pg_bosta_islem": "idle in transaction suresi: >=600 sn orta, >=3600 sn yuksek",
    "pg_baglanti": "baglanti doluluk: >=75% orta, >=90% yuksek",
    "pg_xid_yasi": "orta esik: yas >= 2 x autovacuum_freeze_max_age",
    "pg_sequence": "sequence doluluk: >0.8 yuksek, >0.95 kritik",
    "pg_slot": "etkin olmayan slot: yuksek",
    "pg_kullanilmayan_indeks": "10 MB ustu ve idx_scan=0: dusuk (istatistik sifirlanmis olabilir)",
    "pg_mxid": "multixact yasi: >= 2 x autovacuum_multixact_freeze_max_age orta, >= 1,6 milyar kritik",
    "pg_tablo_autovacuum": "tablo duzeyinde kapatilmis autovacuum: orta",
    "pg_replikasyon": "replika gecikmesi: >=60 sn ya da >=1 GB orta, >=600 sn ya da >=16 GB yuksek; akista olmayan replika orta",
    "pg_gecici_dosya": "gecici dosya: gunluk >=10 GB dusuk, >=100 GB orta; olcum penceresi en az 1 gun sayilir, bilinmiyorsa bilgi",
}

T = {  # kontrol -> sablon. Her alan {"tr":..., "en":...}
    "pg_surum_eol": dict(
        baslik={"tr": "PostgreSQL ana sürümü destek dışı ya da bitmek üzere", "en": "PostgreSQL major version is out of support or about to be"},
        neden={"tr": "Destek bitince güvenlik ve veri bozulması düzeltmeleri yayımlanmaz.", "en": "After end of support, security and corruption fixes are no longer released."},
        oneri={"tr": "Desteklenen bir ana sürüme geçiş planlayın. Önce test ortamında, uygulama uyumu ve geri dönüş adımlarıyla.", "en": "Plan an upgrade to a supported major version, first in a test environment with application checks and a rollback plan."},
        risk={"tr": "Orta. Ana sürüm geçişi bakım penceresi ister.", "en": "Medium. A major upgrade needs a maintenance window."},
        geri={"tr": "Eski küme geçişten sonra da korunursa dönülebilir.", "en": "Reversible while the old cluster is kept after the upgrade."}, is_="buyuk"),
    "pg_xid_yasi": dict(
        baslik={"tr": "İşlem kimliği yaşı yüksek", "en": "Transaction ID age is high"},
        neden={"tr": "Yaş sınıra ulaşırsa veritabanı yazmayı durdurur. Dondurma (freeze) işleminin yetişmesi gerekir.", "en": "If the age reaches the limit the database stops accepting writes. Freezing must keep up."},
        oneri={"tr": "Dondurmayı engelleyen uzun işlemleri, hazırlanmış işlemleri ve etkin olmayan replikasyon slotlarını inceleyin. Etkilenen veritabanında planlı VACUUM (FREEZE) düşünün.", "en": "Look for long transactions, prepared transactions and inactive replication slots that block freezing. Consider a planned VACUUM (FREEZE) on the affected database."},
        risk={"tr": "Düşük. VACUUM yük oluşturur, bakım saatinde çalıştırın.", "en": "Low. VACUUM adds load, run it in a quiet period."},
        geri={"tr": "VACUUM geri alınmaz ama zararsızdır.", "en": "VACUUM cannot be undone but is harmless."}, is_="orta"),
    "pg_bosta_islem": dict(
        baslik={"tr": "Uzun süredir açık, boşta işlemler var", "en": "Long-lived idle-in-transaction sessions"},
        neden={"tr": "Açık işlem temizliği (vacuum) ve kilitleri engeller, tablo ve indeks şişmesine yol açar.", "en": "An open transaction blocks vacuum and holds locks, causing table and index bloat."},
        oneri={"tr": "Uygulama ekibiyle bağlantı havuzunu ve işlem sınırlarını gözden geçirin. idle_in_transaction_session_timeout ayarını değerlendirin.", "en": "Review connection pooling and transaction boundaries with the application team. Consider idle_in_transaction_session_timeout."},
        risk={"tr": "Düşük. Zaman aşımı ayarı, bekleyen işlemleri sonlandırabilir.", "en": "Low. A timeout setting can end waiting transactions."},
        geri={"tr": "Ayar eski değerine döndürülür.", "en": "Set the parameter back to its previous value."}, is_="kucuk"),
    "pg_baglanti": dict(
        baslik={"tr": "Bağlantı sınırına yaklaşılıyor", "en": "Connection count is close to the limit"},
        neden={"tr": "Sınır dolarsa yeni bağlantılar reddedilir.", "en": "When the limit is reached new connections are refused."},
        oneri={"tr": "Bağlantı havuzlayıcı kullanın, uygulama havuz boyutlarını azaltın. max_connections yalnızca son çare olarak artırılmalı (bellek maliyeti).", "en": "Use a connection pooler and reduce application pool sizes. Raise max_connections only as a last resort (memory cost)."},
        risk={"tr": "Orta. max_connections değişikliği yeniden başlatma ister.", "en": "Medium. Changing max_connections needs a restart."},
        geri={"tr": "Ayar geri alınır, yeniden başlatma gerekir.", "en": "Revert the setting; a restart is needed."}, is_="orta"),
    "pg_olu_satir": dict(
        baslik={"tr": "Ölü satır oranı yüksek tablolar", "en": "Tables with a high dead-row ratio"},
        neden={"tr": "Temizlik yetişmiyorsa tablo şişer, sorgular yavaşlar.", "en": "If cleanup lags, tables bloat and queries slow down."},
        oneri={"tr": "Bu tablolar için autovacuum ayarlarını (scale_factor, cost) tablo bazında gözden geçirin; temizliği engelleyen uzun işlem var mı bakın.", "en": "Review per-table autovacuum settings (scale_factor, cost) and check for long transactions blocking cleanup."},
        risk={"tr": "Düşük.", "en": "Low."}, geri={"tr": "Tablo ayarı sıfırlanır.", "en": "Reset the table setting."}, is_="orta"),
    "pg_gecersiz_indeks": dict(
        baslik={"tr": "Geçersiz indeks var", "en": "Invalid indexes exist"},
        neden={"tr": "Geçersiz indeks sorgulara yardım etmez ama yazma maliyeti getirir; yarım kalmış CREATE INDEX CONCURRENTLY sonucu olabilir.", "en": "An invalid index does not help queries but still costs on writes; often left by a failed CREATE INDEX CONCURRENTLY."},
        oneri={"tr": "İndeksi yeniden oluşturun (REINDEX CONCURRENTLY) ya da gerekli değilse kaldırın.", "en": "Rebuild the index (REINDEX CONCURRENTLY) or drop it if not needed."},
        risk={"tr": "Düşük. Yoğun yazma altında yeniden oluşturma süresi uzar.", "en": "Low. Rebuilding takes longer under heavy writes."},
        geri={"tr": "Kaldırılan indeks yeniden oluşturulabilir.", "en": "A dropped index can be recreated."}, is_="kucuk"),
    "pg_kullanilmayan_indeks": dict(
        baslik={"tr": "Büyük ve hiç kullanılmamış indeksler", "en": "Large indexes that were never used"},
        neden={"tr": "Kullanılmayan indeks disk ve yazma maliyeti getirir. İstatistikler sıfırlanmışsa sonuç yanıltıcı olabilir.", "en": "Unused indexes cost disk and write time. Results can mislead if statistics were reset."},
        oneri={"tr": "İstatistik sıfırlama zamanını ve tüm replikalardaki kullanımı kontrol edin; emin olunca kaldırmayı değerlendirin.", "en": "Check when statistics were last reset and usage on all replicas; consider dropping once sure."},
        risk={"tr": "Orta. Dönemsel raporlar indeksi kullanıyor olabilir.", "en": "Medium. Periodic reports may rely on the index."},
        geri={"tr": "İndeks tanımı saklanırsa yeniden oluşturulur.", "en": "Recreate from the saved definition."}, is_="kucuk"),
    "pg_sequence": dict(
        baslik={"tr": "Sequence değeri sınıra yaklaşıyor", "en": "Sequence is approaching its limit"},
        neden={"tr": "Sınıra ulaşan sequence ekleme işlemlerini hataya düşürür.", "en": "A sequence that reaches its maximum makes inserts fail."},
        oneri={"tr": "İlgili kolonu bigint yapmayı ya da sequence sınırını planlayın.", "en": "Plan to widen the column to bigint or adjust the sequence limit."},
        risk={"tr": "Orta. Büyük tablolarda tür değişikliği uzun sürer.", "en": "Medium. Type changes on large tables take long."},
        geri={"tr": "Tür değişikliği geri alınmaz, önce kopya üzerinde deneyin.", "en": "A type change is not reversible, rehearse on a copy first."}, is_="orta"),
    "pg_slot": dict(
        baslik={"tr": "Etkin olmayan ya da WAL biriktiren replikasyon slotu", "en": "Inactive or WAL-retaining replication slot"},
        neden={"tr": "Kullanılmayan slot WAL biriktirir, diski doldurabilir ve dondurmayı engeller.", "en": "An unused slot retains WAL, can fill the disk and blocks freezing."},
        oneri={"tr": "Slotun sahibini belirleyin. Artık gerekmiyorsa kaldırın, gerekiyorsa tüketicisini onarın.", "en": "Find the slot's owner. Drop it if no longer needed, otherwise fix its consumer."},
        risk={"tr": "Orta. Kullanımdaki bir slotun kaldırılması replikayı yeniden kurmayı gerektirir.", "en": "Medium. Dropping a slot in use forces a replica rebuild."},
        geri={"tr": "Kaldırılan slot geri gelmez.", "en": "A dropped slot does not come back."}, is_="kucuk"),
    "pg_arsiv": dict(
        baslik={"tr": "WAL arşivleme sorunu ya da kapalı", "en": "WAL archiving failing or off"},
        neden={"tr": "Arşivsiz çalışan sistemde belirli bir ana geri dönüş (PITR) mümkün olmaz.", "en": "Without archiving, point-in-time recovery is not possible."},
        oneri={"tr": "Arşiv komutunun hata nedenini sunucu günlüğünde inceleyin. Arşiv kapalıysa yedekleme stratejisini gözden geçirin.", "en": "Check the server log for why the archive command fails. If archiving is off, review the backup strategy."},
        risk={"tr": "Düşük. archive_mode değişikliği yeniden başlatma ister.", "en": "Low. Changing archive_mode needs a restart."},
        geri={"tr": "Ayar geri alınır.", "en": "Revert the setting."}, is_="orta"),
    "pg_tls": dict(
        baslik={"tr": "TLS kapalı ya da eski protokol sürümüne izin veriliyor", "en": "TLS is off or old protocol versions are allowed"},
        neden={"tr": "Şifresiz bağlantılarda parolalar ve veriler ağda okunabilir.", "en": "Without TLS, passwords and data can be read on the network."},
        oneri={"tr": "ssl ayarını açın, ssl_min_protocol_version değerini TLSv1.2 ya da üstü yapın, istemcileri sertifika doğrulamalı bağlanacak şekilde güncelleyin.", "en": "Turn ssl on and set ssl_min_protocol_version to TLSv1.2 or higher, and have clients connect with certificate verification."},
        risk={"tr": "Orta. Eski istemciler bağlanamayabilir.", "en": "Medium. Old clients may fail to connect."},
        geri={"tr": "Ayar geri alınır, yapılandırma yeniden yüklenir.", "en": "Revert the setting and reload."}, is_="orta"),
    "pg_parola_md5": dict(
        baslik={"tr": "Parola özeti MD5 olarak saklanıyor", "en": "Password hashes are stored as MD5"},
        neden={"tr": "MD5 parola özeti zayıftır ve PostgreSQL'de kullanımdan kalkmıştır.", "en": "MD5 password hashing is weak and deprecated in PostgreSQL."},
        oneri={"tr": "password_encryption ayarını scram-sha-256 yapın, rollerin parolalarını sırayla yenileyin, pg_hba.conf kurallarını scram'a çevirin.", "en": "Set password_encryption to scram-sha-256, renew role passwords in turn and switch pg_hba.conf rules to scram."},
        risk={"tr": "Orta. Eski istemci kütüphaneleri scram desteklemeyebilir.", "en": "Medium. Old client libraries may not support scram."},
        geri={"tr": "Eski parola özeti geri yüklenemez, önce istemci uyumunu doğrulayın.", "en": "The old hash cannot be restored, verify client compatibility first."}, is_="orta"),
    "pg_super": dict(
        baslik={"tr": "Süper kullanıcı rolleri", "en": "Superuser roles"},
        neden={"tr": "Süper kullanıcılar tüm yetki denetimlerini aşar. Sayı azaltılmalı, oturum açanlar gözden geçirilmeli.", "en": "Superusers bypass all permission checks. Keep the number small and review those that can log in."},
        oneri={"tr": "Günlük işler için süper kullanıcı olmayan, gerekli yetkilere sahip roller kullanın.", "en": "Use non-superuser roles with the specific privileges needed for daily work."},
        risk={"tr": "Düşük.", "en": "Low."}, geri={"tr": "Yetki geri verilebilir.", "en": "Privileges can be granted back."}, is_="kucuk"),
    "pg_tarama_super": dict(
        baslik={"tr": "Tarama süper kullanıcıyla çalıştırılmış", "en": "The scan was run as a superuser"},
        neden={"tr": "Tarama için pg_monitor üyeliği yeterlidir. Süper kullanıcıyla çalışan bir araç, hata ya da kötüye kullanımda bütün sunucuyu etkileyebilir.",
               "en": "Membership in pg_monitor is enough for the scan. A tool running as a superuser can affect the whole server if it fails or is misused."},
        oneri={"tr": "Sonraki taramayı sitedeki alig-rol.sql ile oluşturulan, süper kullanıcı olmayan rolle çalıştırın.",
               "en": "Run the next scan with the non-superuser role created by alig-rol.sql from the site."},
        risk={"tr": "Yok.", "en": "None."}, geri={"tr": "Uygulanmaz.", "en": "Not applicable."}, is_="kucuk"),
    "pg_public_create": dict(
        baslik={"tr": "public şemasında herkes nesne oluşturabiliyor", "en": "Anyone can create objects in the public schema"},
        neden={"tr": "PostgreSQL 14 ve öncesinde varsayılan budur; yetkisiz nesne ve arama yolu saldırılarına kapı açar.", "en": "This is the default in PostgreSQL 14 and earlier and enables unauthorised objects and search-path attacks."},
        oneri={"tr": "PUBLIC rolünden public şemasındaki CREATE yetkisini kaldırmayı değerlendirin.", "en": "Consider revoking CREATE on the public schema from PUBLIC."},
        risk={"tr": "Orta. Bu yetkiye güvenen uygulamalar hata verebilir.", "en": "Medium. Applications relying on it may break."},
        geri={"tr": "Yetki geri verilir.", "en": "Grant it back."}, is_="kucuk"),
    "pg_autovacuum": dict(
        baslik={"tr": "Autovacuum kapalı ya da çalışamıyor", "en": "Autovacuum is off or cannot work"},
        neden={"tr": "Autovacuum kapalıyken ölü satırlar temizlenmez ve istatistikler eskir; track_counts kapalıysa autovacuum hangi tabloya bakacağını bilemez. Tablolar şişer, işlem kimliği yaşı yükselir.",
               "en": "With autovacuum off, dead rows are not cleaned up and statistics go stale; with track_counts off, autovacuum cannot tell which tables need work. Tables bloat and transaction ID age climbs."},
        oneri={"tr": "autovacuum ve track_counts ayarlarını açın. Bazı tablolar farklı davranış istiyorsa tablo düzeyinde ayar kullanın.",
               "en": "Turn autovacuum and track_counts on. If some tables need different behaviour, use table-level settings."},
        risk={"tr": "Düşük. Açıldıktan sonra birikmiş temizlik bir süre yük oluşturabilir.", "en": "Low. After enabling, the cleanup backlog can add load for a while."},
        geri={"tr": "Ayar geri alınır, yapılandırma yeniden yüklenir.", "en": "Revert the setting and reload."}, is_="kucuk"),
    "pg_tablo_autovacuum": dict(
        baslik={"tr": "Autovacuum'u kapatılmış tablolar", "en": "Tables with autovacuum disabled"},
        neden={"tr": "Bu tablolarda ölü satırlar yalnız elle çalıştırılan VACUUM ile temizlenir; elle bakım aksarsa tablo şişer. Dondurma için zorunlu temizlik yine çalışır ama geç ve ağır olur.",
               "en": "Dead rows in these tables are only cleaned by manual VACUUM; if manual maintenance lapses the table bloats. Wraparound-prevention vacuums still run, but late and heavy."},
        oneri={"tr": "Ayarın bilerek kapatıldığını doğrulayın. Gerekmiyorsa ALTER TABLE ... RESET (autovacuum_enabled) ile açın; gerekiyorsa elle VACUUM'u düzenli bir işe bağlayın.",
               "en": "Confirm the setting was turned off on purpose. If not needed, re-enable it with ALTER TABLE ... RESET (autovacuum_enabled); if needed, schedule manual VACUUM."},
        risk={"tr": "Düşük.", "en": "Low."}, geri={"tr": "Tablo ayarı yeniden kapatılabilir.", "en": "The table setting can be turned off again."}, is_="kucuk"),
    "pg_mxid_yasi": dict(
        baslik={"tr": "Multixact yaşı yüksek", "en": "Multixact ID age is high"},
        neden={"tr": "Satır kilitleri ve yabancı anahtar denetimleri multixact kimliği tüketir. Yaş sınıra ulaşırsa veritabanı yazmayı durdurur; dondurma işleminin yetişmesi gerekir.",
               "en": "Row locks and foreign key checks consume multixact IDs. If the age reaches the limit the database stops accepting writes; freezing must keep up."},
        oneri={"tr": "Dondurmayı engelleyen uzun işlemleri ve hazırlanmış işlemleri inceleyin. Etkilenen veritabanında planlı VACUUM (FREEZE) ve autovacuum_multixact_freeze_max_age ayarını değerlendirin.",
               "en": "Look for long transactions and prepared transactions that block freezing. Consider a planned VACUUM (FREEZE) on the affected database and review autovacuum_multixact_freeze_max_age."},
        risk={"tr": "Düşük. VACUUM yük oluşturur, bakım saatinde çalıştırın.", "en": "Low. VACUUM adds load, run it in a quiet period."},
        geri={"tr": "VACUUM geri alınmaz ama zararsızdır.", "en": "VACUUM cannot be undone but is harmless."}, is_="orta"),
    "pg_replikasyon": dict(
        baslik={"tr": "Replika geride kalıyor ya da akışta değil", "en": "A replica is falling behind or not streaming"},
        neden={"tr": "Geride kalan replika, yük devrinde veri kaybına ya da uzun toparlanmaya yol açar; okuma yükü taşıyorsa eski veri döndürür.",
               "en": "A lagging replica means data loss or a long recovery on failover, and stale reads if it serves read traffic."},
        oneri={"tr": "Replika sunucusunda disk ve ağ hızını, yeniden oynatmayı bekleten uzun sorguları (max_standby_streaming_delay, hot_standby_feedback) inceleyin. Akışta olmayan replikanın bağlantısına ve günlüğüne bakın.",
               "en": "On the replica, check disk and network throughput and long queries that hold up replay (max_standby_streaming_delay, hot_standby_feedback). For a replica that is not streaming, check its connection and log."},
        risk={"tr": "Düşük. İnceleme salt okunurdur; ayar değişikliği yeniden yükleme ister.", "en": "Low. The investigation is read-only; setting changes need a reload."},
        geri={"tr": "Ayar geri alınır.", "en": "Revert the setting."}, is_="orta"),
    "pg_sorgu_istatistigi": dict(
        baslik={"tr": "Sorgu istatistikleri (pg_stat_statements) toplanmıyor", "en": "Query statistics (pg_stat_statements) are not collected"},
        neden={"tr": "pg_stat_statements olmadan hangi sorguların zaman ve kaynak tükettiği ölçülemez; performans incelemesinde kanıt eksik kalır.",
               "en": "Without pg_stat_statements there is no measurement of which queries consume time and resources; performance investigations lack evidence."},
        oneri={"tr": "shared_preload_libraries ayarına pg_stat_statements ekleyin (yeniden başlatma gerekir), izlenecek veritabanında CREATE EXTENSION pg_stat_statements çalıştırın, pg_stat_statements.track değerini top bırakın.",
               "en": "Add pg_stat_statements to shared_preload_libraries (needs a restart), run CREATE EXTENSION pg_stat_statements in the database you monitor, and keep pg_stat_statements.track at top."},
        risk={"tr": "Düşük. Küçük bir ek yük ve bellek kullanımı getirir; yeniden başlatma bakım penceresi ister.", "en": "Low. Small overhead and memory use; the restart needs a maintenance window."},
        geri={"tr": "Kütüphane listeden çıkarılır, sunucu yeniden başlatılır.", "en": "Remove the library from the list and restart."}, is_="kucuk"),
    "pg_gecici_dosya": dict(
        baslik={"tr": "Sorgular geçici dosyaya yazıyor", "en": "Queries spill to temporary files"},
        neden={"tr": "work_mem'e sığmayan sıralama ve birleştirmeler diske yazar; sorgular yavaşlar, disk G/Ç'si artar. İstatistiklerin başlangıç zamanı bilinmiyorsa yoğunluk ölçülemez, yalnız kullanım görülür.",
               "en": "Sorts and hashes that do not fit in work_mem write to disk, slowing queries and adding I/O. If the statistics start time is unknown, the rate cannot be measured; only the usage is visible."},
        oneri={"tr": "log_temp_files ile geçici dosya yazan sorguları belirleyin; o sorguları iyileştirin ya da work_mem'i yalnız gereken oturumlarda artırın. Genel work_mem artışı bellek tüketimini katlar.",
               "en": "Use log_temp_files to find the queries that write temporary files; tune them, or raise work_mem only for the sessions that need it. Raising work_mem globally multiplies memory use."},
        risk={"tr": "Düşük. log_temp_files günlük hacmini artırır.", "en": "Low. log_temp_files increases log volume."},
        geri={"tr": "Ayar geri alınır.", "en": "Revert the setting."}, is_="orta"),
    "pg_log": dict(
        baslik={"tr": "Bağlantı günlüğü kapalı", "en": "Connection logging is off"},
        neden={"tr": "Bağlantı ve bağlantı kesme günlüğü olmadan olay incelemesi eksik kalır.", "en": "Without connection and disconnection logs, incident review is incomplete."},
        oneri={"tr": "log_connections ve log_disconnections ayarlarını açın. Günlük hacmini izleyin.", "en": "Enable log_connections and log_disconnections. Watch log volume."},
        risk={"tr": "Düşük. Günlük hacmi artar.", "en": "Low. Log volume grows."},
        geri={"tr": "Ayar geri alınır.", "en": "Revert the setting."}, is_="kucuk"),
}


def _f(kontrol, sablon, onem, kanit_):
    t = T[sablon]
    return {"kontrol": kontrol, "sablon": sablon, "onem": onem, "baslik": t["baslik"], "neden": t["neden"],
            "oneri": t["oneri"], "risk": t["risk"], "geri_alma": t["geri"], "is": t["is_"], "kanit": kanit_}


def _parse_utc(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _nesne(x, *alanlar):
    """Kanit listesi icin nesne adi; veritabani basina denetimlerde veritabani adi one eklenir."""
    return ".".join(str(x[a]) for a in (("veritabani",) if x.get("veritabani") is not None else ()) + alanlar)


def _t(tr, en):
    return {"tr": tr, "en": en}


KURALLAR = []
kural = kanit.kayitci(KURALLAR, "postgresql")
K = kanit.Kaynak
# Kural kaynagi olmayan, raporda bilgi olarak kullanilan denetimler
BILGI = ("pg_sunucu_rolu", "pg_hesap", "pg_kapsam", "pg_eklentiler")   # pg_hesap ve pg_sunucu_rolu sonucun tamligi icin (tarama/kanit.py)

TLS_SURUMLERI = ("TLSv1", "TLSv1.1", "TLSv1.2", "TLSv1.3")
_ACIK, _KAPALI = {"on", "true", "yes", "1"}, {"off", "false", "no", "0"}
# PostgreSQL 18: log_connections asama listesi alir; bos liste kapali demektir.
_BAGLANTI_ASAMALARI = {"receipt", "authentication", "authorization", "setup_durations", "all"}


def _gunluk_acik(deger, liste=False):
    """True, False ya da taninmayan deger icin None."""
    d = deger.strip().lower()
    if d in _ACIK:
        return True
    if d in _KAPALI or (liste and d == ""):
        return False
    if liste and {p.strip() for p in d.split(",")} <= _BAGLANTI_ASAMALARI:
        return True
    return None


# Kural sirasi bulgularin ayni onemdeki sirasidir; kimlikler kalicidir, yeni kural yeni numara alir.

@kural("PG-MAINT-001", "bakim", "yuksek", "HIGH", [K("pg_surum", "tek", ("surum_num",))],
       _t("Ana sürüm desteği", "Major version support"),
       _t("Ana sürümün topluluk desteği en az 90 gün daha sürüyor.", "Community support for the major version lasts at least 90 more days."))
def _surum(r, g):
    if r[0]["surum_num"] < 90000:
        raise kanit.Belirsiz("gecersiz_veri")
    major = r[0]["surum_num"] // 10000
    g.gozle(surum=major)
    eol = PG_EOL.get(major)
    if eol is None and major < min(PG_EOL):
        return [_f("pg_surum", "pg_surum_eol", "yuksek", {"surum": major, "destek_sonu": "gecmis"})]
    if eol:
        gun = (datetime.strptime(eol, "%Y-%m-%d").replace(tzinfo=timezone.utc) - g.taranan).days
        if gun < 0:
            return [_f("pg_surum", "pg_surum_eol", "yuksek", {"surum": major, "destek_sonu": eol})]
        if gun <= 90:
            return [_f("pg_surum", "pg_surum_eol", "orta", {"surum": major, "destek_sonu": eol, "kalan_gun": gun})]
    return []


@kural("PG-MAINT-002", "bakim", "kritik", "HIGH", [K("pg_xid_yasi", "en_az_bir", ("yas",))],
       _t("İşlem kimliği yaşı (wraparound)", "Transaction ID age (wraparound)"),
       _t("Her veritabanında işlem kimliği yaşı autovacuum_freeze_max_age değerinin iki katından ve 1,6 milyardan küçük.",
          "In every database the transaction ID age is below twice autovacuum_freeze_max_age and below 1.6 billion."))
def _xid(r, g):
    worst = max(r, key=lambda x: x["yas"])
    g.gozle(en_yuksek_yas=worst["yas"])
    esik_orta = 2 * (worst.get("freeze_max_age") or 200000000)
    if worst["yas"] >= 1600000000:
        on = "kritik"
    elif worst["yas"] >= esik_orta:
        on = "orta"
    else:
        return []
    return [_f("pg_xid_yasi", "pg_xid_yasi", on,
               {"veritabani": worst["datname"], "yas": worst["yas"], "esik_kritik": 1600000000, "esik_orta": esik_orta})]


@kural("PG-PERF-001", "performans", "yuksek", "MEDIUM", [K("pg_bosta_islem", "herhangi", ("sure_sn",))],
       _t("Boşta bekleyen açık işlemler", "Idle-in-transaction sessions"),
       _t("Tarama anında 10 dakikadan uzun süredir boşta bekleyen açık işlem yok.", "At scan time no transaction has been idle for more than 10 minutes."))
def _bosta(r, g):
    uzun = [x for x in r if x["sure_sn"] >= 600]
    if not uzun:
        return []
    en = max(x["sure_sn"] for x in uzun)
    return [_f("pg_bosta_islem", "pg_bosta_islem", "yuksek" if en >= 3600 else "orta",
               {"oturum_sayisi": len(uzun), "en_uzun_sn": en, "esik_orta_sn": 600, "esik_yuksek_sn": 3600})]


def _kutuphaneler(deger):
    """shared_preload_libraries -> kucuk harfli kutuphane adlari: tirnak, $libdir/ yolu ve .so eki atilir."""
    adlar = []
    for parca in deger.split(","):
        ad = parca.strip().strip('"').strip().rsplit("/", 1)[-1].lower()
        if ad.endswith(".so"):
            ad = ad[:-3]
        if ad:
            adlar.append(ad)
    return adlar


@kural("PG-PERF-002", "performans", "dusuk", "HIGH", [K("pg_sorgu_istatistigi", "tek", ("shared_preload_libraries",))],
       _t("Sorgu istatistikleri (pg_stat_statements)", "Query statistics (pg_stat_statements)"),
       _t("pg_stat_statements shared_preload_libraries ile yüklü ve sorgu topluyor (pg_stat_statements.track: top ya da all).",
          "pg_stat_statements is loaded through shared_preload_libraries and collecting (pg_stat_statements.track: top or all)."))
def _sorgu_istatistigi(r, g):
    yuklu = "pg_stat_statements" in _kutuphaneler(r[0]["shared_preload_libraries"])
    izleme = r[0].get("izleme")
    g.gozle(yuklu=yuklu, izleme=izleme)
    if not yuklu:
        return [_f("pg_sorgu_istatistigi", "pg_sorgu_istatistigi", "dusuk", {"yuklu": False})]
    if izleme is None:
        raise kanit.Belirsiz("eksik_veri")
    if izleme == "none":
        return [_f("pg_sorgu_istatistigi", "pg_sorgu_istatistigi", "dusuk", {"yuklu": True, "pg_stat_statements.track": "none"})]
    if izleme not in ("top", "all"):
        raise kanit.Belirsiz("gecersiz_veri")
    return []


@kural("PG-PERF-003", "performans", "orta", "MEDIUM", [K("pg_gecici_dosya", "en_az_bir", ("dosya", "bayt"))],
       _t("Geçici dosyalar", "Temporary files"),
       _t("Geçici dosya yazılmamış ya da istatistik başlangıcı bilinen her veritabanında günde ortalama 10 GB'ın altında; "
          "başlangıcı bilinmeyen kullanım bilgi olarak gösterilir.",
          "No temporary files were written, or less than 10 GB per day on average in every database with a known statistics "
          "start; usage with an unknown start is shown as information."))
def _gecici_dosya(r, g):
    if any(x["bayt"] < 0 or x["dosya"] < 0 for x in r):
        raise kanit.Belirsiz("gecersiz_veri")
    g.gozle(gecici_bayt=sum(x["bayt"] for x in r), gecici_dosya=sum(x["dosya"] for x in r))
    olculen, bilinmeyen = [], 0
    for x in r:
        if x["bayt"] == 0:
            continue
        t = _parse_utc(x.get("sifirlama_utc"))
        if t is None:
            if x.get("sifirlama_utc") is not None:
                raise kanit.Belirsiz("gecersiz_veri")
            bilinmeyen += 1
            continue
        gun = max((g.taranan - t).total_seconds() / 86400, 1.0)   # kisa pencere hizi buyutmesin
        olculen.append((x["bayt"] / gun, gun, x))
    en = max(olculen, key=lambda o: o[0]) if olculen else None
    if en and en[0] >= 100 * GB:
        on = "orta"
    elif en and en[0] >= 10 * GB:
        on = "dusuk"
    elif bilinmeyen:
        on = "bilgi"
    else:
        return []
    kanit_ = {"pencere_bilinmeyen_veritabani": bilinmeyen, "esik_dusuk_gunluk": 10 * GB, "esik_orta_gunluk": 100 * GB}
    if en:
        kanit_.update(veritabani=en[2]["datname"], gunluk_bayt=int(en[0]), olcum_gunu=round(en[1], 1))
    return [_f("pg_gecici_dosya", "pg_gecici_dosya", on, kanit_)]


@kural("PG-CAP-001", "kapasite", "yuksek", "MEDIUM", [K("pg_baglanti", "tek", ("kullanilan", "ust"))],
       _t("Bağlantı doluluğu", "Connection usage"),
       _t("Tarama anında istemci bağlantıları max_connections değerinin %75'inden az.", "At scan time client connections are below 75% of max_connections."))
def _baglanti(r, g):
    kullanilan, ust = r[0]["kullanilan"], r[0]["ust"]
    if ust <= 0 or kullanilan < 0:
        raise kanit.Belirsiz("gecersiz_veri")
    g.gozle(kullanilan=kullanilan, ust=ust)
    oran = kullanilan / ust
    if oran < 0.75:
        return []
    return [_f("pg_baglanti", "pg_baglanti", "yuksek" if oran >= 0.9 else "orta",
               {"kullanilan": kullanilan, "ust": ust, "oran": round(oran, 3), "esik_orta": 0.75, "esik_yuksek": 0.9})]


@kural("PG-MAINT-003", "bakim", "orta", "MEDIUM", [K("pg_olu_satir", "herhangi", ("canli", "olu"))],
       _t("Ölü satır oranı", "Dead row ratio"),
       _t("10 000'den çok ölü satırı olan tablolarda ölü satır oranı %20'yi geçmiyor.", "In tables with more than 10,000 dead rows the dead-row ratio stays below 20%."),
       birincil=True)   # yedekte n_dead_tup tutulmaz
def _olu_satir(r, g):
    kotu = [x for x in r if x["olu"] / max(x["canli"] + x["olu"], 1) > 0.2]
    if not kotu:
        return []
    return [_f("pg_olu_satir", "pg_olu_satir", "orta",
               {"tablo_sayisi": len(kotu), "nesneler": [_nesne(x, "schemaname", "relname") for x in kotu[:10]],
                "esik_oran": 0.2, "kaynak": "autovacuum_vacuum_scale_factor varsayilani"})]


@kural("PG-MAINT-004", "bakim", "yuksek", "HIGH", [K("pg_gecersiz_indeks")],
       _t("Geçersiz indeksler", "Invalid indexes"),
       _t("Geçersiz (indisvalid = false) indeks yok.", "There are no invalid indexes (indisvalid = false)."))
def _gecersiz_indeks(r, g):
    if not r:
        return []
    return [_f("pg_gecersiz_indeks", "pg_gecersiz_indeks", "yuksek",
               {"indeks_sayisi": len(r), "nesneler": [_nesne(x, "schemaname", "indexrelname") for x in r[:10]]})]


@kural("PG-MAINT-005", "bakim", "dusuk", "LOW", [K("pg_kullanilmayan_indeks")],
       _t("Kullanılmayan büyük indeksler", "Large unused indexes"),
       _t("İstatistiklere göre hiç taranmamış, 10 MB'tan büyük, tekil olmayan indeks yok.",
          "There is no non-unique index over 10 MB that statistics show as never scanned."),
       birincil=True)   # yedekteki idx_scan yalniz yedegin okumalarini sayar
def _kullanilmayan_indeks(r, g):
    if not r:
        return []
    return [_f("pg_kullanilmayan_indeks", "pg_kullanilmayan_indeks", "dusuk",
               {"indeks_sayisi": len(r), "toplam_bayt": sum(x["bayt"] or 0 for x in r),
                "nesneler": [_nesne(x, "schemaname", "indexrelname") for x in r[:10]]})]


@kural("PG-MAINT-006", "bakim", "yuksek", "HIGH", [K("pg_autovacuum", "en_az_bir", ("name", "setting"))],
       _t("Autovacuum", "Autovacuum"),
       _t("autovacuum ve track_counts açık.", "autovacuum and track_counts are on."),
       kaynak=("autovacuum", "track_counts"))
def _autovacuum(r, g):
    ayar = {x["name"]: x["setting"] for x in r}
    if "autovacuum" not in ayar or "track_counts" not in ayar:
        raise kanit.Belirsiz("eksik_veri")
    g.gozle(autovacuum=ayar["autovacuum"], track_counts=ayar["track_counts"])
    acik = {a: _gunluk_acik(ayar[a]) for a in ("autovacuum", "track_counts")}
    if None in acik.values():
        raise kanit.Belirsiz("gecersiz_veri")
    kapali = [a for a, v in acik.items() if v is False]
    if kapali:
        return [_f("pg_autovacuum", "pg_autovacuum", "yuksek", {"kapali_ayarlar": kapali})]
    return []


@kural("PG-MAINT-007", "bakim", "orta", "HIGH", [K("pg_tablo_autovacuum", "herhangi", ("relname",))],
       _t("Tablo düzeyinde kapatılmış autovacuum", "Autovacuum turned off per table"),
       _t("Hiçbir tabloda autovacuum_enabled kapalı değil.", "No table has autovacuum_enabled turned off."))
def _tablo_autovacuum(r, g):
    g.gozle(tablo=len(r))
    if not r:
        return []
    return [_f("pg_tablo_autovacuum", "pg_tablo_autovacuum", "orta",
               {"tablo_sayisi": len(r), "nesneler": [_nesne(x, "schemaname", "relname") for x in r[:10]]})]


@kural("PG-MAINT-008", "bakim", "kritik", "HIGH", [K("pg_xid_yasi", "en_az_bir", ("mxid_yas", "mxid_freeze_max_age"))],
       _t("Multixact yaşı (wraparound)", "Multixact ID age (wraparound)"),
       _t("Her veritabanında multixact yaşı autovacuum_multixact_freeze_max_age değerinin iki katından ve 1,6 milyardan küçük.",
          "In every database the multixact ID age is below twice autovacuum_multixact_freeze_max_age and below 1.6 billion."))
def _mxid(r, g):
    worst = max(r, key=lambda x: x["mxid_yas"])
    if worst["mxid_yas"] < 0 or worst["mxid_freeze_max_age"] <= 0:
        raise kanit.Belirsiz("gecersiz_veri")
    g.gozle(en_yuksek_mxid_yas=worst["mxid_yas"])
    esik_orta = 2 * worst["mxid_freeze_max_age"]
    if worst["mxid_yas"] >= 1600000000:
        on = "kritik"
    elif worst["mxid_yas"] >= esik_orta:
        on = "orta"
    else:
        return []
    return [_f("pg_xid_yasi", "pg_mxid_yasi", on,
               {"veritabani": worst["datname"], "mxid_yas": worst["mxid_yas"], "esik_kritik": 1600000000, "esik_orta": esik_orta})]


@kural("PG-CAP-002", "kapasite", "kritik", "HIGH",
       [K("pg_sequence", "herhangi", ("oran",)), K("pg_sequence_gorunurluk", "en_az_bir", ("okunamayan",), ek=True)],
       _t("Sequence doluluğu", "Sequence exhaustion"),
       _t("Bütün sequence'lar okunabiliyor ve her biri en büyük değerinin %80'inin altında.",
          "Every sequence is readable and below 80% of its maximum value."))
def _sequence(r, g):
    # pg_sequences.last_value, USAGE ya da SELECT yetkisi olmayan sequence icin bos doner: o sequence'lar burada
    # hic gorunmez. Okunamayan varsa sonuc "temiz" sayilmaz.
    gorunurluk = g.satirlar("pg_sequence_gorunurluk")
    if gorunurluk is not None and sum(x["okunamayan"] for x in gorunurluk) > 0:
        g.kismi("kismi_yetki")
    if not r:
        return []
    en = max(x["oran"] for x in r)
    if en <= 0.8:
        return []
    return [_f("pg_sequence", "pg_sequence", "kritik" if en > 0.95 else "yuksek",
               {"sequence_sayisi": len([x for x in r if x["oran"] > 0.8]), "en_yuksek_oran": en,
                "nesneler": [_nesne(x, "schemaname", "sequencename") for x in r if x["oran"] > 0.8][:10]})]


@kural("PG-HA-001", "ha_dr", "kritik", "HIGH", [K("pg_slot", "herhangi", ("active",))],
       _t("Replikasyon slotları", "Replication slots"),
       _t("Bütün replikasyon slotları etkin ve hiçbiri WAL kaybetmemiş (lost, unreserved değil).",
          "All replication slots are active and none has lost WAL (not lost or unreserved)."))
def _slot(r, g):
    if not r:
        raise kanit.Uygulanmaz("slot_yok")
    kotu = [x for x in r if x["active"] is False or x.get("wal_status") in ("lost", "unreserved")]
    g.gozle(slot=len(r))
    if not kotu:
        return []
    lost = any(x.get("wal_status") == "lost" for x in kotu)
    return [_f("pg_slot", "pg_slot", "kritik" if lost else "yuksek",
               {"slot_sayisi": len(kotu), "nesneler": [x["slot_name"] for x in kotu[:10]],
                "geri_bayt_en_fazla": max((x.get("geri_bayt") or 0) for x in kotu)})]


GB = 1024 ** 3
_AKIS_DISI = "backup"   # pg_basebackup baglantisi da pg_stat_replication'da gorunur: replika degildir


@kural("PG-HA-002", "ha_dr", "yuksek", "MEDIUM", [K("pg_replikasyon", "herhangi", ("durum",))],
       _t("Replikasyon gecikmesi", "Replication lag"),
       _t("Bu sunucudan beslenen her replika akışta (streaming) ve yeniden oynatma gecikmesi 60 saniyenin ve 1 GB'ın altında.",
          "Every replica fed by this server is streaming, with replay lag below 60 seconds and 1 GB."))
def _replikasyon(r, g):
    replikalar = [x for x in r if x["durum"] != _AKIS_DISI]
    if not replikalar:
        raise kanit.Uygulanmaz("replika_yok")
    kotu = []
    for x in replikalar:
        sn, bayt = x.get("gecikme_sn"), x.get("gecikme_bayt")
        if bayt is None:   # konum bilinmiyor: gecikme olculemedi (sure gecikmesi yetisen replikada NULL olabilir, bayt olamaz)
            raise kanit.Belirsiz("eksik_veri")
        if bayt < 0 or (sn is not None and sn < 0):
            raise kanit.Belirsiz("gecersiz_veri")
        sn = sn or 0
        if sn >= 600 or bayt >= 16 * GB:
            kotu.append((x, "yuksek"))
        elif sn >= 60 or bayt >= GB or x["durum"] != "streaming":
            kotu.append((x, "orta"))
    en_sn = max((x.get("gecikme_sn") or 0) for x in replikalar)
    en_bayt = max(x["gecikme_bayt"] for x in replikalar)
    g.gozle(replika=len(replikalar), en_yuksek_gecikme_sn=en_sn, en_yuksek_gecikme_bayt=en_bayt)
    if not kotu:
        return []
    return [_f("pg_replikasyon", "pg_replikasyon", "yuksek" if any(o == "yuksek" for _, o in kotu) else "orta",
               {"replika_sayisi": len(replikalar), "sorunlu_replika": len(kotu), "en_yuksek_gecikme_sn": en_sn,
                "en_yuksek_gecikme_bayt": en_bayt, "durumlar": sorted({x["durum"] for x, _ in kotu}),
                "nesneler": [str(x.get("uygulama")) for x, _ in kotu[:10]],
                "esik_orta": "60 sn ya da 1 GB", "esik_yuksek": "600 sn ya da 16 GB"})]


@kural("PG-BACKUP-001", "yedek", "yuksek", "HIGH", [K("pg_arsiv", "tek", ("archive_mode",))],
       _t("WAL arşivleme", "WAL archiving"),
       _t("archive_mode açık, başarılı arşivleme kaydı var ve son hata son başarıdan eski.",
          "archive_mode is on, a successful archive is recorded and the last failure is older than the last success."),
       birincil=True)   # arsivlemeyi birincil yapar
def _arsiv(r, g):
    a = r[0]
    g.gozle(archive_mode=a["archive_mode"], son_basari_utc=a.get("son_basari_utc"))
    if a["archive_mode"] == "off":
        return [_f("pg_arsiv", "pg_arsiv", "orta", {"archive_mode": "off"})]
    hata, basari = _parse_utc(a.get("son_hata_utc")), _parse_utc(a.get("son_basari_utc"))
    if a["archive_mode"] not in ("on", "always") or (a.get("son_hata_utc") is not None and hata is None) \
            or (a.get("son_basari_utc") is not None and basari is None):
        raise kanit.Belirsiz("gecersiz_veri")
    if hata and (not basari or hata > basari):
        return [_f("pg_arsiv", "pg_arsiv", "yuksek", {"son_hata_utc": a["son_hata_utc"], "son_basari_utc": a.get("son_basari_utc")})]
    if not basari:
        raise kanit.Belirsiz("arsiv_kaniti_yok")   # arsivleme acik ama calistigina dair kayit yok
    return []


@kural("PG-SEC-001", "guvenlik", "yuksek", "HIGH", [K("pg_tls_parola", "tek", ("ssl",))],
       _t("TLS", "TLS"),
       _t("ssl açık ve en düşük protokol sürümü TLSv1.2 ya da üstü.", "ssl is on and the minimum protocol version is TLSv1.2 or later."),
       kaynak=("ssl", "ssl_min_protocol_version"))
def _tls(r, g):
    t = r[0]
    g.gozle(ssl=t["ssl"], ssl_min_protocol_version=t.get("ssl_min_protocol_version"))
    if t["ssl"] == "off":
        return [_f("pg_tls_parola", "pg_tls", "yuksek", {"ssl": t["ssl"]})]
    if t["ssl"] != "on":
        raise kanit.Belirsiz("gecersiz_veri")
    surum = t.get("ssl_min_protocol_version")
    if surum is None:
        raise kanit.Belirsiz("eksik_veri")
    if surum not in TLS_SURUMLERI:
        raise kanit.Belirsiz("gecersiz_veri")
    if surum in ("TLSv1", "TLSv1.1"):
        return [_f("pg_tls_parola", "pg_tls", "yuksek", {"ssl_min_protocol_version": surum})]
    return []


@kural("PG-SEC-002", "guvenlik", "orta", "HIGH", [K("pg_tls_parola", "tek", ("password_encryption",))],
       _t("Parola özeti ayarı", "Password hashing setting"),
       _t("password_encryption değeri scram-sha-256.", "password_encryption is scram-sha-256."),
       kaynak=("password_encryption",))
def _parola_ayari(r, g):
    pe = r[0]["password_encryption"]
    g.gozle(password_encryption=pe)
    if pe == "md5":
        return [_f("pg_tls_parola", "pg_parola_md5", "orta", {"password_encryption": "md5"})]
    if pe != "scram-sha-256":
        raise kanit.Belirsiz("gecersiz_veri")
    return []


@kural("PG-SEC-003", "guvenlik", "orta", "HIGH", [K("pg_md5_roller", "tek", ("sayi",))],
       _t("MD5 özetli rol parolaları", "Role passwords stored as MD5"),
       _t("MD5 özetiyle saklanan rol parolası yok (pg_authid okuma yetkisi gerekir).",
          "No role password is stored as an MD5 hash (requires read access to pg_authid)."))
def _md5_roller(r, g):
    sayi = r[0]["sayi"]
    if sayi < 0:
        raise kanit.Belirsiz("gecersiz_veri")
    g.gozle(md5_rol_sayisi=sayi)
    if sayi > 0:
        return [_f("pg_md5_roller", "pg_parola_md5", "orta", {"md5_rol_sayisi": sayi, "roller": True})]
    return []


@kural("PG-SEC-004", "guvenlik", "orta", "HIGH", [K("pg_super_roller", "herhangi", ("rolcanlogin",))],
       _t("Oturum açabilen süper kullanıcılar", "Superusers that can log in"),
       _t("Oturum açabilen süper kullanıcı rolü yok.", "No superuser role can log in."))
def _super_roller(r, g):
    oturum = [x for x in r if x["rolcanlogin"] is True]
    g.gozle(oturum_acabilen_super=len(oturum))
    if not oturum:
        return []
    return [_f("pg_super_roller", "pg_super", "dusuk" if len(oturum) <= 2 else "orta",
               {"oturum_acabilen_super_sayisi": len(oturum), "nesneler": [x["rolname"] for x in oturum[:10]]})]


@kural("PG-SEC-005", "guvenlik", "orta", "HIGH", [K(kanit.TOPLAYICI, "tek", ("superuser",))],
       _t("Taramanın hesabı", "Scan account"),
       _t("Tarama süper kullanıcı olmayan bir rolle çalıştırıldı.", "The scan ran with a role that is not a superuser."),
       kaynak=("is_superuser",))
def _tarama_hesabi(r, g):
    g.gozle(super_kullanici=r[0]["superuser"])
    if r[0]["superuser"] is True:
        return [_f(kanit.TOPLAYICI, "pg_tarama_super", "orta", {"tarama_super_kullanici_ile_calisti": True})]
    return []


@kural("PG-SEC-006", "guvenlik", "orta", "HIGH", [K("pg_public_create", "en_az_bir", ("public_create",))],
       _t("public şemasında CREATE yetkisi", "CREATE on the public schema"),
       _t("Hiçbir veritabanında PUBLIC rolü public şemasında nesne oluşturamıyor.", "In no database can PUBLIC create objects in the public schema."))
def _public_create(r, g):
    acik = [x for x in r if x["public_create"] is True]
    g.gozle(acik_veritabani=len(acik))
    if not acik:
        return []
    return [_f("pg_public_create", "pg_public_create", "orta",
               {"public_create": True, "veritabanlari": [str(x.get("veritabani")) for x in acik[:10]]})]


@kural("PG-SEC-007", "guvenlik", "dusuk", "HIGH", [K("pg_log_ayarlari", "en_az_bir", ("name", "setting"))],
       _t("Bağlantı günlüğü", "Connection logging"),
       _t("log_connections ve log_disconnections açık.", "log_connections and log_disconnections are on."))
def _gunluk(r, g):
    ayar = {x["name"]: x["setting"] for x in r}
    if "log_connections" not in ayar or "log_disconnections" not in ayar:
        raise kanit.Belirsiz("eksik_veri")
    g.gozle(log_connections=ayar["log_connections"], log_disconnections=ayar["log_disconnections"])
    baglanti, kesme = _gunluk_acik(ayar["log_connections"], liste=True), _gunluk_acik(ayar["log_disconnections"])
    if baglanti is False or kesme is False:
        return [_f("pg_log_ayarlari", "pg_log", "dusuk", {k: ayar[k] for k in ("log_connections", "log_disconnections")})]
    if baglanti is None or kesme is None:
        raise kanit.Belirsiz("gecersiz_veri")
    return []


def incele(doc):
    """Ortak kanit modeli: her kural icin bir kayit, iki motor icin ayni bicim (tarama/kanit.py)."""
    if isinstance(doc, dict) and doc.get("motor") == "mssql":
        from tarama import kurallar_mssql
        return kanit.calistir(doc, kurallar_mssql.KURALLAR, katalog.MSSQL_BY_ID, kurallar_mssql.TURLER)
    return kanit.calistir(doc, KURALLAR, katalog.PG_BY_ID, yukleme.TURLER)


def degerlendir(doc):
    """(bulgular, olculemeyenler). olculemeyen = [(kural_kimligi, neden)]: durumu UNKNOWN ya da UNAVAILABLE olan kurallar."""
    s = incele(doc)
    return s.bulgular, s.olculemeyen

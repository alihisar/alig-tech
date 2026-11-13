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
BILGI = ("pg_kapsam", "pg_eklentiler")

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

@kural("PG-MAINT-001", "bakim", "HIGH", [K("pg_surum", "tek", ("surum_num",))],
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


@kural("PG-MAINT-002", "bakim", "HIGH", [K("pg_xid_yasi", "en_az_bir", ("yas",))],
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


@kural("PG-PERF-001", "performans", "MEDIUM", [K("pg_bosta_islem", "herhangi", ("sure_sn",))],
       _t("Boşta bekleyen açık işlemler", "Idle-in-transaction sessions"),
       _t("Tarama anında 10 dakikadan uzun süredir boşta bekleyen açık işlem yok.", "At scan time no transaction has been idle for more than 10 minutes."))
def _bosta(r, g):
    uzun = [x for x in r if x["sure_sn"] >= 600]
    if not uzun:
        return []
    en = max(x["sure_sn"] for x in uzun)
    return [_f("pg_bosta_islem", "pg_bosta_islem", "yuksek" if en >= 3600 else "orta",
               {"oturum_sayisi": len(uzun), "en_uzun_sn": en, "esik_orta_sn": 600, "esik_yuksek_sn": 3600})]


@kural("PG-CAP-001", "kapasite", "MEDIUM", [K("pg_baglanti", "tek", ("kullanilan", "ust"))],
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


@kural("PG-MAINT-003", "bakim", "MEDIUM", [K("pg_olu_satir", "herhangi", ("canli", "olu"))],
       _t("Ölü satır oranı", "Dead row ratio"),
       _t("10 000'den çok ölü satırı olan tablolarda ölü satır oranı %20'yi geçmiyor.", "In tables with more than 10,000 dead rows the dead-row ratio stays below 20%."))
def _olu_satir(r, g):
    kotu = [x for x in r if x["olu"] / max(x["canli"] + x["olu"], 1) > 0.2]
    if not kotu:
        return []
    return [_f("pg_olu_satir", "pg_olu_satir", "orta",
               {"tablo_sayisi": len(kotu), "nesneler": [_nesne(x, "schemaname", "relname") for x in kotu[:10]],
                "esik_oran": 0.2, "kaynak": "autovacuum_vacuum_scale_factor varsayilani"})]


@kural("PG-MAINT-004", "bakim", "HIGH", [K("pg_gecersiz_indeks")],
       _t("Geçersiz indeksler", "Invalid indexes"),
       _t("Geçersiz (indisvalid = false) indeks yok.", "There are no invalid indexes (indisvalid = false)."))
def _gecersiz_indeks(r, g):
    if not r:
        return []
    return [_f("pg_gecersiz_indeks", "pg_gecersiz_indeks", "yuksek",
               {"indeks_sayisi": len(r), "nesneler": [_nesne(x, "schemaname", "indexrelname") for x in r[:10]]})]


@kural("PG-MAINT-005", "bakim", "LOW", [K("pg_kullanilmayan_indeks")],
       _t("Kullanılmayan büyük indeksler", "Large unused indexes"),
       _t("İstatistiklere göre hiç taranmamış, 10 MB'tan büyük, tekil olmayan indeks yok.",
          "There is no non-unique index over 10 MB that statistics show as never scanned."))
def _kullanilmayan_indeks(r, g):
    if not r:
        return []
    return [_f("pg_kullanilmayan_indeks", "pg_kullanilmayan_indeks", "dusuk",
               {"indeks_sayisi": len(r), "toplam_bayt": sum(x["bayt"] or 0 for x in r),
                "nesneler": [_nesne(x, "schemaname", "indexrelname") for x in r[:10]]})]


@kural("PG-CAP-002", "kapasite", "HIGH",
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


@kural("PG-HA-001", "ha_dr", "HIGH", [K("pg_slot", "herhangi", ("active",))],
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


@kural("PG-BACKUP-001", "yedek", "HIGH", [K("pg_arsiv", "tek", ("archive_mode",))],
       _t("WAL arşivleme", "WAL archiving"),
       _t("archive_mode açık, başarılı arşivleme kaydı var ve son hata son başarıdan eski.",
          "archive_mode is on, a successful archive is recorded and the last failure is older than the last success."))
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


@kural("PG-SEC-001", "guvenlik", "HIGH", [K("pg_tls_parola", "tek", ("ssl",))],
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


@kural("PG-SEC-002", "guvenlik", "HIGH", [K("pg_tls_parola", "tek", ("password_encryption",))],
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


@kural("PG-SEC-003", "guvenlik", "HIGH", [K("pg_md5_roller", "tek", ("sayi",))],
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


@kural("PG-SEC-004", "guvenlik", "HIGH", [K("pg_super_roller", "herhangi", ("rolcanlogin",))],
       _t("Oturum açabilen süper kullanıcılar", "Superusers that can log in"),
       _t("Oturum açabilen süper kullanıcı rolü yok.", "No superuser role can log in."))
def _super_roller(r, g):
    oturum = [x for x in r if x["rolcanlogin"] is True]
    g.gozle(oturum_acabilen_super=len(oturum))
    if not oturum:
        return []
    return [_f("pg_super_roller", "pg_super", "dusuk" if len(oturum) <= 2 else "orta",
               {"oturum_acabilen_super_sayisi": len(oturum), "nesneler": [x["rolname"] for x in oturum[:10]]})]


@kural("PG-SEC-005", "guvenlik", "HIGH", [K(kanit.TOPLAYICI, "tek", ("superuser",))],
       _t("Taramanın hesabı", "Scan account"),
       _t("Tarama süper kullanıcı olmayan bir rolle çalıştırıldı.", "The scan ran with a role that is not a superuser."),
       kaynak=("is_superuser",))
def _tarama_hesabi(r, g):
    g.gozle(super_kullanici=r[0]["superuser"])
    if r[0]["superuser"] is True:
        return [_f(kanit.TOPLAYICI, "pg_tarama_super", "orta", {"tarama_super_kullanici_ile_calisti": True})]
    return []


@kural("PG-SEC-006", "guvenlik", "HIGH", [K("pg_public_create", "en_az_bir", ("public_create",))],
       _t("public şemasında CREATE yetkisi", "CREATE on the public schema"),
       _t("Hiçbir veritabanında PUBLIC rolü public şemasında nesne oluşturamıyor.", "In no database can PUBLIC create objects in the public schema."))
def _public_create(r, g):
    acik = [x for x in r if x["public_create"] is True]
    g.gozle(acik_veritabani=len(acik))
    if not acik:
        return []
    return [_f("pg_public_create", "pg_public_create", "orta",
               {"public_create": True, "veritabanlari": [str(x.get("veritabani")) for x in acik[:10]]})]


@kural("PG-SEC-007", "guvenlik", "HIGH", [K("pg_log_ayarlari", "en_az_bir", ("name", "setting"))],
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

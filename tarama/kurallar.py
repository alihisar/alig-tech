"""Toplama dosyasindan bulgu uretir. Dil modeli yok: ayni girdi her zaman ayni bulgulari verir.

Esikler: BELGE = resmi belgede/politikada yazili deger, MUHENDISLIK = kendi secimimiz (docs/doldurulacak.md'de listeli).
Nesne adlari asla baslik/aciklama metnine girmez; yalniz kanit listesinde, kacisli olarak gosterilir.
"""
from datetime import datetime, timezone

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


def _f(kontrol, sablon, onem, kanit):
    t = T[sablon]
    return {"kontrol": kontrol, "sablon": sablon, "onem": onem, "baslik": t["baslik"], "neden": t["neden"],
            "oneri": t["oneri"], "risk": t["risk"], "geri_alma": t["geri"], "is": t["is_"], "kanit": kanit}


def _parse_utc(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# Kural icinde tur ya da anahtar hatasi: o kontrol "gecersiz_veri" ile olculemeyen sayilir, rapor ve panel dusmez.
_VERI_HATASI = (TypeError, KeyError, ValueError, ZeroDivisionError, OverflowError, AttributeError, IndexError)


def degerlendir(doc):
    """(bulgular, olculemeyenler). olculemeyen = [(kontrol_id, neden)]"""
    if doc.get("motor") == "mssql":
        from tarama import kurallar_mssql
        return kurallar_mssql.degerlendir(doc)
    bulgu, olcul = [], []
    k = doc.get("kontroller") or {}
    taranan = _parse_utc(doc.get("olusturma_utc")) or datetime.now(timezone.utc)

    def rows(cid):
        e = k.get(cid)
        if e is None:
            olcul.append((cid, "calistirilmadi"))
            return None
        if not isinstance(e, dict) or e.get("durum") != "ok":
            olcul.append((cid, e.get("neden", "hata") if isinstance(e, dict) else "gecersiz_veri"))
            return None
        r = e.get("satirlar")
        if not isinstance(r, list) or not all(isinstance(x, dict) for x in r):
            olcul.append((cid, "gecersiz_veri"))
            return None
        return r

    def kural(cid):
        """Kural fonksiyonunu kontrol satirlariyla calistirir; veri hatasinda kontrolu olculemeyen sayar."""
        def sar(fn):
            r = rows(cid)
            if not r:
                return fn
            try:
                bulgu.extend(fn(r) or [])
            except _VERI_HATASI:
                olcul.append((cid, "gecersiz_veri"))
            return fn
        return sar

    @kural("pg_surum")
    def _(r):
        major = r[0]["surum_num"] // 10000
        eol = PG_EOL.get(major)
        if eol is None and major < min(PG_EOL):
            return [_f("pg_surum", "pg_surum_eol", "yuksek", {"surum": major, "destek_sonu": "gecmis"})]
        if eol:
            gun = (datetime.strptime(eol, "%Y-%m-%d").replace(tzinfo=timezone.utc) - taranan).days
            if gun < 0:
                return [_f("pg_surum", "pg_surum_eol", "yuksek", {"surum": major, "destek_sonu": eol})]
            if gun <= 90:
                return [_f("pg_surum", "pg_surum_eol", "orta", {"surum": major, "destek_sonu": eol, "kalan_gun": gun})]
        return []

    @kural("pg_xid_yasi")
    def _(r):
        worst = max(r, key=lambda x: x["yas"])
        esik_orta = 2 * (worst.get("freeze_max_age") or 200000000)
        if worst["yas"] >= 1600000000:
            on = "kritik"
        elif worst["yas"] >= esik_orta:
            on = "orta"
        else:
            return []
        return [_f("pg_xid_yasi", "pg_xid_yasi", on,
                   {"veritabani": worst["datname"], "yas": worst["yas"], "esik_kritik": 1600000000, "esik_orta": esik_orta})]

    @kural("pg_bosta_islem")
    def _(r):
        uzun = [x for x in r if (x.get("sure_sn") or 0) >= 600]
        if not uzun:
            return []
        en = max(x["sure_sn"] for x in uzun)
        return [_f("pg_bosta_islem", "pg_bosta_islem", "yuksek" if en >= 3600 else "orta",
                   {"oturum_sayisi": len(uzun), "en_uzun_sn": en, "esik_orta_sn": 600, "esik_yuksek_sn": 3600})]

    @kural("pg_baglanti")
    def _(r):
        if not r[0]["ust"]:
            return []
        oran = r[0]["kullanilan"] / r[0]["ust"]
        if oran < 0.75:
            return []
        return [_f("pg_baglanti", "pg_baglanti", "yuksek" if oran >= 0.9 else "orta",
                   {"kullanilan": r[0]["kullanilan"], "ust": r[0]["ust"], "oran": round(oran, 3), "esik_orta": 0.75, "esik_yuksek": 0.9})]

    @kural("pg_olu_satir")
    def _(r):
        kotu = [x for x in r if x["olu"] and x["canli"] is not None and x["olu"] / max(x["canli"] + x["olu"], 1) > 0.2]
        if not kotu:
            return []
        return [_f("pg_olu_satir", "pg_olu_satir", "orta",
                   {"tablo_sayisi": len(kotu), "nesneler": [f'{x["schemaname"]}.{x["relname"]}' for x in kotu[:10]],
                    "esik_oran": 0.2, "kaynak": "autovacuum_vacuum_scale_factor varsayilani"})]

    @kural("pg_gecersiz_indeks")
    def _(r):
        return [_f("pg_gecersiz_indeks", "pg_gecersiz_indeks", "yuksek",
                   {"indeks_sayisi": len(r), "nesneler": [f'{x["schemaname"]}.{x["indexrelname"]}' for x in r[:10]]})]

    @kural("pg_kullanilmayan_indeks")
    def _(r):
        return [_f("pg_kullanilmayan_indeks", "pg_kullanilmayan_indeks", "dusuk",
                   {"indeks_sayisi": len(r), "toplam_bayt": sum(x["bayt"] or 0 for x in r),
                    "nesneler": [f'{x["schemaname"]}.{x["indexrelname"]}' for x in r[:10]]})]

    @kural("pg_sequence")
    def _(r):
        en = max(x["oran"] for x in r)
        if en <= 0.8:
            return []
        return [_f("pg_sequence", "pg_sequence", "kritik" if en > 0.95 else "yuksek",
                   {"sequence_sayisi": len([x for x in r if x["oran"] > 0.8]), "en_yuksek_oran": en,
                    "nesneler": [f'{x["schemaname"]}.{x["sequencename"]}' for x in r if x["oran"] > 0.8][:10]})]

    @kural("pg_sequence_gorunurluk")
    def _(r):
        # pg_sequences.last_value, USAGE ya da SELECT yetkisi olmayan sequence icin bos doner: o sequence'lar
        # yukaridaki denetimde hic gorunmez. Okunamayan varsa sonuc "temiz" sayilmaz.
        if r[0]["okunamayan"] and r[0]["okunamayan"] > 0:
            olcul.append(("pg_sequence", "kismi_yetki"))
        return []

    @kural("pg_slot")
    def _(r):
        kotu = [x for x in r if x["active"] is False or x.get("wal_status") in ("lost", "unreserved")]
        if not kotu:
            return []
        lost = any(x.get("wal_status") == "lost" for x in kotu)
        return [_f("pg_slot", "pg_slot", "kritik" if lost else "yuksek",
                   {"slot_sayisi": len(kotu), "nesneler": [x["slot_name"] for x in kotu[:10]],
                    "geri_bayt_en_fazla": max((x.get("geri_bayt") or 0) for x in kotu)})]

    @kural("pg_arsiv")
    def _(r):
        a = r[0]
        if a["archive_mode"] == "off":
            return [_f("pg_arsiv", "pg_arsiv", "orta", {"archive_mode": "off"})]
        hata, basari = _parse_utc(a.get("son_hata_utc")), _parse_utc(a.get("son_basari_utc"))
        if hata and (not basari or hata > basari):
            return [_f("pg_arsiv", "pg_arsiv", "yuksek", {"son_hata_utc": a["son_hata_utc"], "son_basari_utc": a.get("son_basari_utc")})]
        return []

    @kural("pg_tls_parola")
    def _(r):
        t, out = r[0], []
        if t["ssl"] != "on":
            out.append(_f("pg_tls_parola", "pg_tls", "yuksek", {"ssl": t["ssl"]}))
        elif t["ssl_min_protocol_version"] in ("TLSv1", "TLSv1.1"):
            out.append(_f("pg_tls_parola", "pg_tls", "yuksek", {"ssl_min_protocol_version": t["ssl_min_protocol_version"]}))
        if t["password_encryption"] == "md5":
            out.append(_f("pg_tls_parola", "pg_parola_md5", "orta", {"password_encryption": "md5"}))
        return out

    @kural("pg_md5_roller")
    def _(r):
        if r[0]["sayi"] > 0 and not any(b["sablon"] == "pg_parola_md5" and "roller" in b["kanit"] for b in bulgu):
            return [_f("pg_md5_roller", "pg_parola_md5", "orta", {"md5_rol_sayisi": r[0]["sayi"], "roller": True})]
        return []

    @kural("pg_super_roller")
    def _(r):
        oturum = [x for x in r if x["rolcanlogin"]]
        if not oturum:
            return []
        return [_f("pg_super_roller", "pg_super", "dusuk" if len(oturum) <= 2 else "orta",
                   {"oturum_acabilen_super_sayisi": len(oturum), "nesneler": [x["rolname"] for x in oturum[:10]]})]

    if doc.get("superuser") is True:
        bulgu.append(_f("pg_super_roller", "pg_super", "orta", {"tarama_super_kullanici_ile_calisti": True}))

    @kural("pg_public_create")
    def _(r):
        return [_f("pg_public_create", "pg_public_create", "orta", {"public_create": True})] if r[0]["public_create"] is True else []

    @kural("pg_log_ayarlari")
    def _(r):
        ayar = {x["name"]: x["setting"] for x in r}
        if ayar.get("log_connections") == "off" or ayar.get("log_disconnections") == "off":
            return [_f("pg_log_ayarlari", "pg_log", "dusuk", {k2: ayar.get(k2) for k2 in ("log_connections", "log_disconnections")})]
        return []

    rows("pg_kapsam")      # bilgi: raporda kapsam olarak yazilir (tarama/rapor.py)
    rows("pg_eklentiler")  # bilgi: kaydedilir, bulgu uretmez
    sira = {o: i for i, o in enumerate(ONEM)}
    bulgu.sort(key=lambda b: sira[b["onem"]])
    return bulgu, olcul

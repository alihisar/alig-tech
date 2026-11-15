# Kararlar

Ali'nin vermesi gereken kararlar tek kimlikle burada izlenir. Kimlikler `docs/master-prompt-v5.md` bölüm 21 ile aynıdır.
Aynı kimlik başka bir karar için kullanılmaz. "Engeller" sütunundaki maddeler karar verilmeden kodlanmaz;
"Varsayılan" sütunu doluysa iş o varsayılanla ilerler ve tek satırla değiştirilebilir kalır.

| Kimlik | Karar | Engeller | Varsayılan / öneri | Durum |
| --- | --- | --- | --- | --- |
| DB-K1 | PostgreSQL sürücü stratejisi: (A) toplayıcının `psql` istemcisini yeniden kullanmak, (B) standart kütüphane `ctypes` + işletim sisteminin `libpq.so.5` kitaplığı, (C) sürümü sabitlenmiş `psycopg` (yalnız kütüphane kuralına istisna verilirse) | ALIG-DB-003 ve sonrası (uygulama kodunun PostgreSQL'e taşınması) | Öneri: **B**. Gerekçe ve karşılaştırma `docs/postgresql-gecis.md` bölüm 2. A işlem (transaction) yönetimi yapamaz; C dış paket kuralını bozar. B'nin değerlendirme prototipi (ALIG-DB-002) karar beklenirken yapılabilir, uygulamaya bağlanmaz. | Ali'yi bekliyor |
| DB-K2 | PostgreSQL 18 kurulum topolojisi: uygulama ile aynı sunucu mu ayrı sunucu mu, staging ayrımı, Unix soketi mi TLS (`verify-full`) mi | Canlı kurulum, `deploy/` PostgreSQL rolü | Varsayılan: aynı sunucuda, yalnız Unix soketi, `peer` yerine `scram-sha-256`; staging ayrı sunucu | Ali'yi bekliyor |
| DB-K3 | Müşteri portalının (madde 16, 17) RLS kapsamı | Portalın canlıda açılması | Portal kodu var ve varsayılan kapalı (`ALIG_PORTAL`). Firma izolasyonu veri katmanında. RLS ayrı tasarımla sonra; o zamana kadar portal kapalı kalır | Varsayılanla ilerliyor |
| DB-K4 | Göç (cutover) bakım penceresi ve geri dönüş sınırı | ALIG-DB-004 Faz D | Yok; cutover yalnız ayrı onayla | Ali'yi bekliyor |
| DB-K5 | RPO/RTO hedefleri | ALIG-DB-005'in "karşılanıyor" denmesi | Yok; ölçüm restore tatbikatıyla yapılır, hedef uydurulmaz | Ali'yi bekliyor |
| WEB-K1 | E-posta gönderim sağlayıcısı (SMTP) | Kayıt e-postası, portal, Kip B'nin genel açılışı | Kod gönderimden bağımsız (madde 15); giden kutusu var | Ali'yi bekliyor |
| WEB-K2 | KVKK aydınlatma, kullanım koşulları, Kip B bağlantı onayı metinleri | Canlıya alma | `[doldurulacak]` alanları `docs/doldurulacak.md` | Ali'yi bekliyor |
| WEB-K3 | Marka varlıkları: logo, arka plan görselleri | Tasarımın son hâli | Yazı tabanlı logo | Varsayılanla ilerliyor |
| WEB-K4 | Barındırma, sunucu IP, sabit çıkış IP, DNS, yayın takvimi | Canlıya alma, Kip B müşteri güvenlik duvarı izni | `docs/dns.md` taslağı | Ali'yi bekliyor |
| WEB-K5 | Dil modeli (LLM) rapor özeti hizmeti | Madde 23'ün açılması | Varsayılan kapalı; kanıt üretemez, puanı değiştiremez. Gerçek sağlayıcıya bağlanan kod yok. KVKK notu: gerçek bir sağlayıcıya veri gönderimi (kural kimliği, durum, önem, başlık bile olsa) hukuki onay gerektirir; onaysız açılmaz | Varsayılanla ilerliyor |
| WEB-K6 | SQL Server'ın gerçek sunucuda denenmesi (madde 22) | SQL Server taramasının yayımlanması | Varsayılan kapalı (`ALIG_MSSQL`) | Ali'yi bekliyor |
| WEB-K7 | Rapor silindikten sonra karşılaştırma özetinin saklanması ve süresi; portal hesabı saklama süresi | İlgili saklama sürelerinin KVKK metnine girmesi | Saklama politikasındaki varsayılanlar | Ali'yi bekliyor |
| GEL-K1 | PostgreSQL geçişi kodunun dalı | — | Varsayılan: ALIG-DB-003 ve ALIG-DB-004 kodu `pg-gecis` dalında geliştirilir ve PR ile birleştirilir; belge ve diğer maddeler `main` dalına gider. Cutover onayı (DB-K4) olmadan `pg-gecis` birleştirilmez | Varsayılanla ilerliyor |

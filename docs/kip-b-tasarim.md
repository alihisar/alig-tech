# Kip B (doğrudan bağlantı): tasarım ve tehdit modeli

Durum: PostgreSQL için ilk dilim kodlandı, **varsayılan olarak kapalı** (`ALIG_DOGRUDAN=1` ile açılır). Canlıya alınmadı.

| Parça | Yer | Durum |
| --- | --- | --- |
| Hedef doğrulaması (iç ağa yönlendirme, DNS rebinding) | `tarama/hedef.py`, `tests/test_hedef.py` | Kodlandı |
| Tarama (sahiplik kanıtı, süper kullanıcı reddi, TLS, sabit katalog) | `tarama/baglanti.py`, `tests/test_baglanti.py` | Kodlandı; gerçek PostgreSQL 16 + TLS ile elle sınandı |
| İstek akışı ve sayfalar | `tarama/server.py` (`/api/tarama/baglan`), `tarama/hata.py` | Kodlandı |
| Firma izni | Yönetim paneli, firma ayrıntısı: "Doğrudan bağlantı izni ver" | Kodlandı |
| Ayrı çalıştırıcı süreci ve systemd birimi | `tarama/calistirici.py`, `tests/test_calistirici.py`, `alig-calistirici.service.j2` | Kodlandı; gerçek sunucuda systemd altında sınanmadı |
| SQL Server | yok | **Yazılmadı** (kanıt yöntemi belirsiz) |

## Tasarımdan sapmalar ve açık kalanlar

- **Çalıştırıcı gerçek sunucuda denenmedi.** Tarama artık ayrı bir süreçte (`alig-calistirici`) koşar: ayrı kullanıcı, veri dizinine ve servis sırlarına erişim yok, iç ağ systemd düzeyinde de yasak. Web süreci parolayı yerel soketten bellekte iletir ve dışarıya bağlanamaz. Canlı başlatıcı (`tarama/server.py`) çalıştırıcı soketi olmadan özelliği açmaz. Birim dosyası, soket izinleri ve `SupplementaryGroups` ayarı gerçek bir systemd üzerinde sınanmadı; `ansible-lint` ve birim testleri geçti. İş kuyruğu yok: istek tarama bitene kadar açık kalır.
- **E-posta doğrulaması yerine yönetici izni.** Gönderim yöntemi seçilmediği için firma kimliği e-postayla doğrulanmıyor. Onun yerine doğrudan bağlantı yalnızca yöneticinin panelden izin verdiği firmalara açık. İzinli bir firmanın e-posta adresini bilen biri onun adına istek açabilir; kendi yönetmediği bir veritabanını yine taratamaz (sahiplik kanıtı gerekir), ama firmanın tarama hakkını harcayabilir.
- **Sunucu sertifikası doğrulanmıyor.** Bağlantı `sslmode=require` ile şifrelidir ama sertifika denetlenmez. `channel_binding=require` eklendi: sunucu SCRAM-SHA-256-PLUS ile kimliğini TLS kanalına bağlamak zorunda, parola düz ya da MD5 ile gönderilmez ve araya giren biri kimlik doğrulamayı aktaramaz. Bedeli: `md5` ya da `password` yöntemiyle doğrulanan hesapla Kip B çalışmaz (hata sayfası SCRAM'ı söyler). `verify-full` için müşteriden CA dosyası alma adımı hâlâ yazılmadı.
- **Hedef adresi saklanıyor.** Sunucu adı ve IP, istek kaydında en çok bir gün durur (taramayı çalıştırmak için gerekir). Denetim kaydına yalnızca özeti yazılır. Parola hiçbir yerde saklanmaz.
- **Port tarama zamanlaması.** Hata iletisi tek tiptir ama yanıt süresi sabitlenmedi. Yalnızca izinli firmalar istek açabildiği ve saatte 5 istek sınırı olduğu için etkisi sınırlıdır.
- **Tarama eşzamanlıdır.** İstek, tarama bitene kadar (en çok yaklaşık 2 dakika) açık kalır. Aynı anda en çok iki tarama çalışır.

## Kip A ile farkı

Kip A'da müşteri betiği kendi ağında çalıştırır, alig.tech hiçbir veritabanına bağlanmaz. Kip B'de müşteri bağlantı bilgisi verir ve tarama alig.tech sunucusundan çalışır. Bu, iki yeni risk getirir: sunucumuz dışarıya bağlantı açan bir araca dönüşür ve müşterinin kimlik bilgisi bir süre bizde durur.

## Önerilen akış

1. Müşteri firma kaydıyla giriş yapar (e-posta doğrulaması zorunlu; bugün yok).
2. Sunucu adresi, port, veritabanı ve tarama hesabının adını yazar. Parola en son adımda, tek seferlik istenir.
3. Sunucu adresi doğrulanır (aşağıdaki SSRF önlemleri) ve müşteriye bir sahiplik kanıtı görevi verilir.
4. Kanıt doğrulanınca tarama, web sürecinden ayrı bir çalıştırıcıda Kip A ile aynı sabit sorgu kataloğuyla çalışır.
5. Parola taramadan hemen sonra bellekten silinir, diske yazılmaz. Rapor Kip A ile aynı yoldan üretilir.

## Tehdit modeli

| Tehdit | Önlem | Sınama |
| --- | --- | --- |
| SSRF: müşteri iç ağımızdaki ya da bulut meta veri servisindeki bir adresi yazar | Ad çözülür, çıkan **her** adres denetlenir: özel (RFC 1918), geri döngü, bağlantı-yerel, CGNAT, çok noktaya yayın, IPv6 eşdeğerleri ve kendi adres aralığımız reddedilir. Yalnızca izinli portlar (varsayılan 5432, 1433 ve müşterinin yazdığı 1024 üstü port) | `test_ic_ve_ozel_adresler_reddedilir`, `test_ipv4_tasiyan_ipv6_bicimleri_reddedilir`, `test_alisilmadik_sayisal_yazimlar_reddedilir`, `test_portlar` |
| DNS rebinding: ad denetimde açık adrese, bağlantıda iç adrese çözülür | Ad bir kez çözülür, bağlantı **çözülen IP'ye** açılır; TLS sunucu adı ayrıca verilir. Yeniden çözümleme yok | `test_rebinding_ikinci_cozumleme_olmaz`, `test_bir_kayit_bile_icse_tumu_reddedilir` |
| Yönlendirme ve vekil üzerinden atlatma | Yalnızca ham TCP üzerinden veritabanı protokolü; HTTP istemcisi kullanılmaz, ortam vekil değişkenleri yok sayılır | Çalıştırıcı ortamının denetimi |
| Başkasının veritabanını taratma | Sahiplik kanıtı: müşteri, tarama hesabına bizim verdiğimiz rastgele değeri taşıyan bir yorum ekler (`COMMENT ON ROLE alig_hc IS 'alig-kanit-<rastgele>'`); tarama önce bunu okur, uyuşmazsa hiçbir sorgu çalışmaz | Kanıtsız ve yanlış kanıtlı bağlantı testleri |
| Port tarama ve hizmet keşfi aracı olarak kötüye kullanım | Hata iletisi tek tiptir ("bağlanılamadı"), süre sabitlenir; firma başına ve hedef başına deneme sınırı; yalnızca doğrulanmış firma | Zamanlama ve ileti testleri |
| Parolanın sızması | Parola yalnızca bellekte, tek tarama boyunca; günlüklere, denetim kaydına, hata iletilerine ve süreç argümanlarına girmez. İstek gövdesi günlüklenmez | Günlük ve denetim kaydında parola araması yapan test |
| Parolanın ağda okunması | Bağlantı TLS ister (`sslmode=require` en az). Sertifika doğrulaması müşteri CA dosyası verirse `verify-full` | TLS'siz sunucuya bağlanmayı reddetme testi |
| Müşteri veritabanında yazma ya da uzun kilit | Kip A ile aynı: sabit katalog, salt okunur oturum, 15 sn sorgu ve 2 sn kilit sınırı, tek bağlantı. Süper kullanıcıyla tarama reddedilir (Kip A'da yalnızca uyarılıyor) | Mevcut katalog testleri ve süper kullanıcı reddi testi |
| Kötü niyetli sunucunun bize zarar vermesi | Sunucudan gelen her değer Kip A'daki yükleme doğrulamasından geçer (katı şema, boyut ve tür sınırı). Çalıştırıcı ayrı kullanıcı, ayrı systemd birimi, dosya sistemine yazma yok, toplam süre ve yanıt boyutu sınırlı | Dev yanıt ve bozuk tür testleri |
| Çalıştırıcının ele geçirilmesi | Çalıştırıcı web sürecinden ve veritabanlarımızdan ayrıdır; iş kuyruğundan yalnızca iş okur, sonucu doğrulanmış JSON olarak geri yazar | Birim dosyası sertleştirme denetimi |
| Hizmet engelleme | Aynı anda sınırlı sayıda tarama, firma başına günlük sınır, kuyruk uzunluğu sınırı | Sınır testleri |
| İnkâr ve iz | Kim, ne zaman, hangi hedef özetine (adresin SHA-256'sı) tarama başlattı denetim zincirine yazılır; adresin kendisi ve parola yazılmaz | Zincir testi |

## Bilinen sınırlar

- Müşteri veritabanını internete açmak zorunda kalır ya da çıkış adresimize izin verir. Çoğu kurum için Kip A daha uygundur; Kip B küçük ekipler içindir.
- Sahiplik kanıtı, tarama hesabında yorum yazabilen birinin onayını gösterir; kurumun onayını göstermez. Sözleşme ve yetki beyanı yine gerekir.
- SQL Server için eşdeğer kanıt yöntemi belirlenmedi (giriş üzerinde yorum yok).

## Karar bekleyenler

1. ~~Kip B yapılacak mı?~~ Yanıt: evet, ilk dilim kodlandı (kapalı).
2. **Sabit çıkış IP adresi:** Müşterinin güvenlik duvarında izin verebilmesi için gerekir; barındırma seçimine bağlı.
3. **E-posta gönderim yöntemi:** Firma doğrulaması olmadan Kip B açılmaz.
4. ~~Parola saklanacak mı?~~ Uygulanan: saklanmaz, her taramada yeniden sorulur. Zamanlanmış tarama istenirse şifreli saklama ve anahtar yönetimi ayrı bir tasarım ister.
5. **Hukuki metin:** Müşterinin bize bağlantı yetkisi verdiğini gösteren onay metni.

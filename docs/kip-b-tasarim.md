# Kip B (doğrudan bağlantı): tasarım ve tehdit modeli

Durum: yalnızca tasarım. **Kod yazılmadı.** Aşağıdaki "Karar bekleyenler" yanıtlanmadan kodlanmaz.

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
| SSRF: müşteri iç ağımızdaki ya da bulut meta veri servisindeki bir adresi yazar | Ad çözülür, çıkan **her** adres denetlenir: özel (RFC 1918), geri döngü, bağlantı-yerel, CGNAT, çok noktaya yayın, IPv6 eşdeğerleri ve kendi adres aralığımız reddedilir. Yalnızca izinli portlar (varsayılan 5432, 1433 ve müşterinin yazdığı 1024 üstü port) | Her yasak aralık için birim testi; IPv4 eşlemeli IPv6, ondalık ve sekizlik yazım, sondaki nokta |
| DNS rebinding: ad denetimde açık adrese, bağlantıda iç adrese çözülür | Ad bir kez çözülür, bağlantı **çözülen IP'ye** açılır; TLS sunucu adı ayrıca verilir. Yeniden çözümleme yok | Sahte çözümleyiciyle iki farklı yanıt testi |
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

1. **Kip B yapılacak mı?** Bankalar ve düzenlemeye tabi kurumlar veritabanını dışarıya açmaz. Hedef müşteri onlarsa Kip B gereksiz risk olabilir.
2. **Sabit çıkış IP adresi:** Müşterinin güvenlik duvarında izin verebilmesi için gerekir; barındırma seçimine bağlı.
3. **E-posta gönderim yöntemi:** Firma doğrulaması olmadan Kip B açılmaz.
4. **Parola hiç saklanmayacak mı?** Öneri: hayır, her taramada yeniden sorulur. Zamanlanmış tarama istenirse şifreli saklama ve anahtar yönetimi ayrı bir tasarım ister.
5. **Hukuki metin:** Müşterinin bize bağlantı yetkisi verdiğini gösteren onay metni.

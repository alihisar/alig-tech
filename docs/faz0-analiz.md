# FAZ 0: mevcut sistem analizi

Kaynak: `docs/master-prompt-v2.md` (Ali'nin 12 Kasım 2026 tarihli geliştirme belgesi). Bu dosya, belgedeki her isteği
koddaki gerçek durumla karşılaştırır. Durumlar: DONE (kod + geçen test), PARTIAL, MISSING, NOT_TESTED, BLOCKED.

Sayılar (12 Kasım 2026): 198 birim testi (2 atlanan: gerçek PostgreSQL isteyenler), 13 CI denetimi, hepsi geçiyor.
Belgedeki "178 test" eski sayıdır; kural aynı kalır: test sayısı düşmez.

## Modül 1: uygulama güvenliği (P0)

| İstek | Durum | Kanıt ya da eksik |
| --- | --- | --- |
| İstek ve dosya boyutu sınırı | DONE | 5 MB, `tarama/yukleme.py` `MAX_BAYT`; `test_yukleme_*` |
| İçerik biçimi, şema ve tür doğrulaması | DONE | Katı şema, bilinmeyen alan ve kolon reddi |
| İç içe derinlik sınırı | DONE (bu adımda) | Derin JSON yakalanmayan `RecursionError` üretiyordu; `MAX_DERINLIK`, `test_derinlik_siniri` |
| Standart dışı JSON (NaN, yinelenen anahtar) | DONE (bu adımda) | `test_standart_disi_json_reddedilir` |
| Liste, satır ve metin uzunluğu sınırı | DONE | `MAX_SATIR`, `MAX_METIN` |
| Geçici dosya, dosya yolu manipülasyonu | DONE | Yükleme diske yazılmaz, dosya adı kullanılmaz |
| Yinelenen yükleme denetimi | MISSING | Aynı dosya iki kez yüklenirse iki hak harcar |
| Firma kotası, IP hız sınırı | DONE | 30 günde 2, IP başına saatte 5 |
| Kullanıcı bazlı hız sınırı | MISSING | Müşteri girişi yok (portal ile gelir) |
| Tarama verisinin yürütülmemesi | DONE | Değerler yalnızca kaçışlı gösterilir |
| Firma izolasyonu, veri katmanında | PARTIAL | Bugün müşteri girişi yok: rapora yalnızca tahmin edilemez bağlantıyla erişilir, firma listeleri yalnızca yönetici panelinde. Portal gelince veri erişim katmanında firma denetimi zorunlu |
| Parola türetme, deneme sınırı, oturum süresi | DONE | scrypt, 5/10 deneme, 30 dk boşta, 8 saat üst sınır |
| Çerez, CSRF, TOTP tekrar kullanımı | DONE | `__Host-` çerez, oturum başına CSRF, `totp_sayac` |
| Parola ya da TOTP değişiminde oturum iptali | DONE | `yonetim/depo.py` |
| Şüpheli girişlerin denetim kaydı | PARTIAL | Başarısız giriş yazılıyor; yeni IP uyarısı yok |
| Rapor bağlantısı: rastgele, süreli, silinebilir | DONE | 32 bayt, veritabanında yalnız SHA-256, 30 gün |
| `Cache-Control: no-store`, `Referrer-Policy` | DONE | `tarama/server.py` |
| Günlükte bağlantı yok | DONE | Yol maskelenir |
| Tek kullanımlık rapor erişimi | MISSING | İsteğe bağlı, düşük öncelik |
| Denetim zinciri | PARTIAL | SHA-256 zinciri var. Anahtarlı doğrulama ve zincir başının bağımsız yerde saklanması yok: veritabanına yazabilen biri zinciri baştan üretebilir |
| Denetim kaydı alanları (firma, hedef, sonuç) | PARTIAL | Aktör, olay, zaman var; alanlar olay metninin içinde, ayrı kolon değil |

## Modül 2: veri gizliliği ve saklama (P0)

| İstek | Durum | Kanıt ya da eksik |
| --- | --- | --- |
| Süresi dolan raporları silme | DONE | `suresi_dolanlari_sil` |
| Müşteri talebiyle rapor silme | DONE | Rapor sayfasındaki düğme |
| Silinen rapora eski bağlantıyla erişilememesi | DONE | Test var; kabul ölçütünün tamamı için ek negatif testler eklenecek |
| Firma silme iş akışı | PARTIAL | Yönetici siler; müşteri talebi akışı yok |
| Firma kaydı saklama süresi | MISSING | Süresiz duruyor |
| Veri sınıfları ve yapılandırılabilir saklama politikası | MISSING | Süreler kod sabiti, sınıf tablosu yok |
| Yedeklerden silme politikası | MISSING | Yedekler 14 adet tutuluyor, silinen veri yedekte kalır; belgelenmedi |
| KVKK metni taslağı | BLOCKED | Hukuki onay ister; yalnızca taslak yazılabilir |

## Modül 3: Health Intelligence v2 (P1)

| İstek | Durum | Kanıt ya da eksik |
| --- | --- | --- |
| Mevcut katalog, toplayıcı, kural sistemi | DONE | 16 PostgreSQL denetimi, kural motoru |
| Sürüm yetenek matrisi (12–18) | MISSING | Katalog 13–18 için yazıldı, yalnızca 16'da sınandı. PostgreSQL 12 destek dışıdır; tanınıp raporlanmalı |
| Durumlar: PASS, FAIL, WARNING, UNKNOWN, NOT_APPLICABLE, UNAVAILABLE | PARTIAL | Bulgu ve "ölçülemedi" var; geçen denetimler ve uygulanamaz durumu ayrı gösterilmiyor |
| Ortak kanıt modeli | PARTIAL | Her bulguda kanıt sözlüğü var; kural kimliği, kategori, güven düzeyi, kaynak alanları yok |
| Sağlık puanı ve kanıt kapsamı | MISSING | |
| Geçmiş karşılaştırması | MISSING | Raporlar firmaya bağlı ama veritabanı kimliği yok |
| Kategoriler: replikasyon gecikmesi, wraparound, autovacuum, `pg_stat_statements`, HBA | PARTIAL | Bir kısmı var; liste madde 12'de genişler |

## Modül 4–8

| Modül | Durum | Not |
| --- | --- | --- |
| Müşteri portalı (`/portal/`) | MISSING | `/demo/` yalnızca istemci tarafı gösterimdir. E-posta gönderimi seçilmeden canlıda açılmaz |
| Kurumsal site | PARTIAL | C teması, TR/EN, canonical, hreflang, sitemap, robots var. Hizmet kartları, "nasıl çalışır", örnek rapor ve SSS bölümleri eksik ya da kısmi |
| Yönetim paneli | PARTIAL | Firma, tarama, talep, denetim, sistem durumu var. Gösterge sayıları ve ticari süreç durumları eksik |
| İş kuyruğu | MISSING | Dosya yüklemede analiz milisaniyeler sürer, kuyruk gerekmez. Kuyruk yalnızca doğrudan bağlantı için gerekir |
| Raporlama | PARTIAL | Tek görünüm, TR/EN, kanıtlı. Yönetici özeti ve teknik rapor ayrımı yok |

## Modül 9–12

| Modül | Durum | Not |
| --- | --- | --- |
| SQL Server | NOT_TESTED | Ön sürüm, kapalı. Gerçek sunucu denemesi Ali'de |
| LLM özeti | MISSING | P2, varsayılan kapalı tasarlanacak |
| Kip B | PARTIAL, kapalı | Belgede P3. Tehdit modeli, hedef doğrulaması, tarama ve ayrı çalıştırıcı yazıldı. Yeni Kip B işi P0 ve P1 bitene kadar durduruldu |
| Canlıya alma | NOT_TESTED | Ansible, nginx, systemd dosyaları var. nginx yapılandırması gerçek nginx ile doğrulandı; hiçbir şey gerçek sunucuda çalıştırılmadı. Yedekleme var, geri yükleme komutu ve testi yok |

## Belgeyle ayrıştığım noktalar

- **PostgreSQL 12:** Topluluk desteği Kasım 2024'te bitti. Yetenek matrisine "destek dışı, tanınır" olarak girer; sorgular 12 için ayrıca sınanamaz (elimde yalnızca 16 var).
- **İş kuyruğu:** Belge her taramayı kuyruğa almayı öneriyor. Dosya yükleme yolu için gereksiz karmaşıklık olur; yalnızca doğrudan bağlantı için önerilir.
- **Kip B:** Belgede P3, kodda öne alınmış durumda. Geri alınmadı, kapalı tutuluyor.
- **Denetim zinciri:** Anahtarlı doğrulama, anahtar aynı sunucuda durduğu sürece tam çözüm değildir. Zincir başının dışarıya (örneğin yedek hedefine) düzenli yazılması da gerekir; hedef seçimi Ali'de.

## Açık P0 riskleri

1. Denetim zinciri veritabanına yazabilen biri tarafından yeniden üretilebilir.
2. Firma kayıtları süresiz saklanıyor; saklama politikası ve veri sınıfları tanımlı değil.
3. Yedekten geri yükleme hiç denenmedi.
4. Hiçbir şey gerçek sunucuda çalıştırılmadı.
5. Hukuki metinler yok (engelleyen karar).

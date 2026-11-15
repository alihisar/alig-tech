# Değişiklik günlüğü

## Yayınlanmadı

- Güvenlik denetimi ALIG-SEC-001 (yönetim ve rapor erişimi): 47 yeni negatif test (`tests/test_erisim_guvenligi.py`): firma belirteci başka firmanın raporunu açamaz/silemez/doğrulayamaz, süresi dolan ve silinen raporun bütün uçları kapalı, yönetim uçlarının tamamı (tablo güdümlü, 25 GET ve 10 POST yolu) her geçersiz oturum durumunda girişe gider ve veri sızdırmaz, CSV yalnız oturumlu, rapor ve panel HTML kaçışı, TOTP tekrar kullanımı ve oturum kodunun yalnız SHA-256 özetiyle saklanması, TOTP kurtarma. Gerçek açık çıkmadı; düzeltme: `yonetim/kullanici.py` gevşek umask'ta `yonetim.sqlite`'ı 0644 oluşturuyordu, artık 0600. Açık: TOTP sırrı veritabanında düz metin (standart kütüphanede şifre yok); karar SEC-K1 `docs/kararlar.md`de. Bulgular `docs/kod-inceleme.md`de; `docs/runbook.md`ye "Doğrulama cihazı kaybı" prosedürü eklendi.
- Örnek rapor sayfası (`/ornek-rapor/` yönetici özeti, `/ornek-rapor-teknik/` teknik rapor; TR ve EN, üç tema): sentetik, uydurma nesne adlı bir tarama belgesinden `tarama/uret_ornek_rapor.py` ile üretilir (müşteri raporuyla aynı kod yolu, `site/uretilen/`, elle düzenlenmez; CI güncellik denetimi). Sayfa başında ve yazdırmada görünen etiket: sentetik test verisinden üretildi, gerçek bir müşteriye ait değildir. Silme ve doğrulama eylemi yok. Ana sayfadaki sağlık taraması adımları ve sağlık taraması sayfası örnek rapora bağlanır. `rapor.govde` sekme adresleri ve silinme tarihsiz rapor için iki isteğe bağlı değer aldı; varsayılan davranış aynı.
- PostgreSQL sürücü değerlendirmesi (ALIG-DB-002, yalnız prototip, uygulamaya bağlı değil): `ortak/pg.py`, `ctypes` + sistem `libpq` ile dar sarmalayıcı (parametreli sorgu, işlem, zaman aşımı, `PQcancel`, SQLSTATE hata sınıfları, parola maskeleme); `tests/test_pg_prototip.py` PG16 geçici kümesinde 25 test. Ölçüm ve DB-K1 önerisi `docs/postgresql-gecis.md` bölüm 2'de; PG18 sınanmadı.
- Tarama güvenliği denetimi (ALIG-SCAN-001): Kip B hedef doğrulamasında IPv6 kapsam kimliği (`[2606:...%x hostaddr=127.0.0.1]`) bağlantı dizgisine girip `hostaddr`/`options` anahtarlarını ezerek iç ağ reddini atlatabiliyordu; kapsam kimlikli adresler artık reddediliyor ve `baglanti_dizgisi` host, IP ve portu kendisi de doğruluyor. Kip B `psql` çıktısı 2 MB ile sınırlandı (düşmanca sunucu bellek şişiremez), veritabanı/kullanıcı adındaki sondaki satır sonu reddediliyor. Yeni `tests/test_tarama_guvenlik.py` (52 test): tüm toplayıcı ve Kip B SQL metinleri için allowlist, salt okunur oturum ve zaman aşımı, SSRF tablosu, kaynak sınırları, Kip B kapalıyken 404. Toplayıcı kaynağı değişmedi.
- Yönetim paneli: Özet sayfasında gösterge (son 7 ve 30 gün tarama, aktif ve pasif firma, açık iletişim, portal ve Kip B talepleri, giden kutusunda bekleyen posta, iki denetim zincirinin doğrulaması; salt okuma, okunamayan sayı "veri yok" gösterilir). Firma başına ticari süreç durumu (aday, görüşülüyor, teklif, müşteri, kapandı) ve notu: geçersiz geçiş reddedilir, geçiş iki denetim zincirine yazılır (not yazılmaz), firma sayfasında değişir, listede süzülür. Not firma kaydıyla birlikte silinir (`docs/saklama-politikasi.md`). Ek göç (SQLite, mevcut çalışma zamanı).
- Dil modeli rapor özeti (madde 23), varsayılan kapalı: `tarama/ozet_llm.py` takılabilir sağlayıcı arayüzü. Gerçek sağlayıcı ve ağ çağrısı yok (WEB-K5), yalnız test için sahte sağlayıcı. Açmak için `ALIG_LLM_OZET=1` ve kayıtlı sağlayıcı gerekir. Sağlayıcıya yalnız kural kimliği, durum, önem ve maskelenmiş başlık gider. Çıktı girdide olmayan kural kimliği, sayı, "PASS/geçti" iddiası, uzunluk ve kontrol karakteri için doğrulanır; reddedilen ya da hata veren özet gösterilmez, içerik yazılmadan günlüğe olay yazılır. Yönetici görünümünde ayrı kutuda "kanıt değildir" etiketiyle gösterilir; puan ve bulgular özetten bağımsızdır. Kapalıyken rapor çıktısı değişmez. TR ve EN.
- Yol haritası: Master Prompt v5 (v4.1 dahil) maddeleri eklendi; PostgreSQL geçişi (ALIG-DB-001…006), güvenlik ve tarama denetimleri (ALIG-SEC-001, ALIG-SCAN-001), PostgreSQL CI (ALIG-CI-001, 002). Günde iki maddelik plan. Yeni belgeler: `docs/kararlar.md`, `docs/postgresql-gecis.md`, `docs/master-prompt-v5.md`. Kod değişmedi.
- Ana sayfa: 7 hizmet kartı (sağlık denetimi, yönetilen operasyon, yüksek erişilebilirlik, güvenlik sertleştirme, performans, sürüm yükseltme ve göç, danışmanlık), "sağlık taraması nasıl çalışır" dört adımı ve altı soruluk SSS; üç temada, TR ve EN. Sürüm desteği SSS'de olduğu gibi yazılır: yalnız PostgreSQL 16 gerçek sunucuda sınandı. Tema C'de ajan bölümünün bağlantı kimliği `#ajan` oldu; `#hizmetler` hizmet kartlarına gider.
- Müşteri portalı, ikinci dilim (varsayılan kapalı): tarama geçmişinde önceki taramaya göre puan değişimi, rapor silme
  (onay sayfası, form kodu, yalnız kendi firması), ücretsiz tarama hakkı ve yenilenme tarihi, hizmet talebi (günde en
  çok 5), hesap ve veri silme talebi (yalnız kayıt; silme yönetici işlemi). Yönetim panelinde Portal talepleri sayfası:
  durum değişimi iki denetim zincirine de yazılır. TR ve EN.
- Müşteri portalı, ilk dilim (`/portal/`, varsayılan kapalı): hesap isteği ve tek kullanımlık, süreli e-posta doğrulaması
  (GET hiçbir şey değiştirmez, hesap düğmeyle açılır), parola girişi (scrypt, deneme sınırı), oturum, rapor listesi ve
  görüntüleme. Firma izolasyonu veri erişim katmanındadır: her sorgu oturumdaki kullanıcının firmasına bağlıdır, başka
  firmanın raporu tahmin edilen kimlikle bulunamaz ve var olmayan kimlikle aynı yanıtı verir. Hesap varlığı ekrandan
  anlaşılmaz. Yalnız e-posta doğrulaması açıkken açılır (`ALIG_PORTAL=1`, `musteri_portali`). Parola sıfırlama yok.
- Rapor görünümleri: `?gorunum=yonetici` yönetici özeti (genel durum, en önemli 5 risk ve olası iş etkisi, öncelik sıralı
  öneriler, önceki taramaya göre değişim, kanıt türü: kesin kanıt, istatistik, hipotez), `?gorunum=teknik` (varsayılan)
  teknik rapor. Özet yalnız kural çıktısından üretilir, dil modeli yok. Kanıtı eksik tarama temiz sayılmaz. Bulgu
  kartında Kanıt ve Yorum ayrı bloklardır; bulgu varken “Değişiklikten önce ve sonra” bölümü yer alır. Yazdırma düzeni
  eklendi (sekmeler ve silme düğmesi gizlenir). Müşteri raporunda ve yönetim panelinde aynı. TR ve EN.
- Sağlık taraması: geçmiş karşılaştırması (`tarama/gecmis.py`). Toplayıcı küme tanımlayıcısının yalnız SHA-256 özetini
  gönderir; aynı firmanın aynı sunucudan (aynı rol) yaptığı önceki tarama, saklama süresi dolmadıysa raporda
  karşılaştırılır: önceki ve yeni puan, kapsam değişimi, her denetim için yeni, kötüleşen, süren, çözülen, bilinmeyen.
  Önceki sorun bu taramada ölçülemiyorsa çözüldü sayılmaz. Panelde de görünür; görüntüleme denetim kaydına yazılır.
- Sağlık taraması: altı yeni PostgreSQL kuralı: autovacuum ve track_counts, tablo düzeyinde kapatılmış autovacuum,
  multixact yaşı, replikasyon gecikmesi (süre ve bayt), pg_stat_statements, geçici dosyalar. Toplayıcı sunucunun
  birincil mi yedek mi olduğunu kaydeder; yedekte tablo istatistiğine ve arşivlemeye dayanan kurallar Uygulanmaz
  (yedekte ölü satır kuralı veri yokken temiz çıkıyordu). Slot sorgusu yedek sunucuda hata veriyordu, düzeltildi. Hepsi
  gerçek PostgreSQL 16 birincil ve akışlı yedek sunucuda sınandı; raporda sunucu rolü satırı.
- Sağlık taraması: sağlık puanı (0–100) ve kanıt kapsamı (`tarama/puan.py`). Her kural bir risk düzeyi taşır; puan risk
  ağırlıklı kredi oranıdır. Bilinmiyor ve Alınamadı, Başarısız kadar puan kaybettirir: eksik ya da kaybolan veri puanı
  yükseltmez. Raporda özet satırları, kategori tablosu ve puanı düşüren denetimler (bulgu ve kanıt eksikliği ayrı);
  yönetim panelinde Puan sütunu ve etkin katsayılar. Katsayılar `ALIG_PUAN_AYARI` ile verilen JSON dosyasından
  ayarlanır, geçersiz dosyayla servisler başlamaz. Raporun kanıt listesinde evet/hayır değerleri artık Türkçe/İngilizce
  yazılır; bulgusuz raporda Bulgular başlığının altı boş kalmaz.
- Sağlık taraması: PostgreSQL sürüm ve yetki matrisi. Toplayıcı ve doğrudan bağlantı sunucunun ana sürümünü okur, o sürümün
  sorgusunu seçer, desteklenmeyen sürümde sorguyu hiç çalıştırmaz (PostgreSQL 12 için ayrı slot sorgusu). Yeni `pg_hesap`
  denetimi tarama hesabının rollerini okur; `pg_monitor` içindeki gerekli rol yoksa kural Geçti olamaz (gerçek PostgreSQL 16'da
  yetkisiz hesap başka oturumları göremiyordu). Sınanmayan sürümde kanıt güveni en çok orta. `tarama/surum_dogrula.py` gerçek
  sunucuda üç hesapla doğrulama yapar; sonuç `docs/surum-matrisi.md`.
- Sağlık taraması: ortak kanıt modeli (`tarama/kanit.py`). Her kural kalıcı bir kimlikle (PG-SEC-001 gibi) her taramada
  tek durum üretir: FAIL, WARNING, UNKNOWN, UNAVAILABLE, NOT_APPLICABLE, PASS; kategori, güven düzeyi, kaynak, gözlenen
  değerler. Veri eksik, kısmi ya da bozukken PASS çıkmaz. Raporda denetim sonuçları tablosu, bulgu kartında kural ve kaynak.
  Kural listesi `docs/kural-katalogu.md` dosyasına üretilir. PostgreSQL 18'in `log_connections` liste değerleri tanınır.
- Depo iskeleti, standart kütüphane derleyicisi (TR/EN), yerel OFL yazı tipleri.
- CI denetimleri: dış kaynak, boyut bütçesi, sır, doldurulacak alan, dil eşliği,
  bağlantı, HTML yapısı, yasaklı kalıplar.
- Ana sayfa için iki tasarım yönü taslağı (A: Konsol, B: Rapor).

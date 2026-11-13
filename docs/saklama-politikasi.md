# Veri sınıfları ve saklama politikası

Kaynak: `tarama/saklama.py` (tek yer). Süreler ortamdan ayarlanır: `ALIG_SAKLAMA_<SINIF>_GUN` (`/etc/alig/env`). `0` ya da `suresiz` yalnız suresiz seçilebilen sınıflarda geçerlidir; geçersiz değerde servisler ve bakım işi açık hata ile durur, sessizce varsayılana dönmez.

**Varsayılan süreler hukuken onaylanmış değerler değildir.** Hukuk onayı gelene kadar taslaktır `[doldurulacak: saklama sürelerinin hukuki onayı]`.

| Sınıf | Varsayılan | Nerede | Ne zaman silinir |
| --- | --- | --- | --- |
| `rapor` | 30 gün | tarama.sqlite | Oluşturulurken bitiş tarihi yazılır; günlük bakım ve müşteri/yönetici silme düğmesi siler |
| `baglanti_istegi` | 1 gün | tarama.sqlite | Süresi dolan Kip B isteği (parola hiç saklanmaz) |
| `firma` | 365 gün | tarama.sqlite | Son etkinlikten sonra ve etkin raporu yoksa; silme `sistem` olarak denetime yazılır, firma adı ve e-postası denetime yazılmaz |
| `talep` | 365 gün | form.sqlite, yonetim.sqlite | Oluşturulmasından sonra; durum notları da silinir, işlem yönetim zincirine yazılır |
| `denetim` | süresiz | tüm zincirler | Silinmez: silme zinciri bozar. Zincir başı dışa aktarılarak korunur (`docs/runbook.md`) |

Geçmiş karşılaştırması (`tarama/gecmis.py`) yeni veri saklamaz: yalnız saklama süresi dolmamış raporları okur. Rapor silinince ya da süresi dolunca o tarama karşılaştırmaya da girmez. Daha uzun geçmiş için özet saklama ayrı bir veri sınıfı ve hukuk onayı ister `[doldurulacak: karşılaştırma özeti saklama kararı]`.

Müşteri portalı (`ALIG_PORTAL`, varsayılan kapalı) yeni veri sınıfı ekler: portal hesabı (e-posta, scrypt parola özeti, dil). Hesap, firma silinince (yukarıdaki `firma` süresi) birlikte silinir; doğrulanmamış hesap isteği ve doğrulama kodu 24 saatte, oturum bostayken 30 dakikada (en çok 8 saat), giriş denemesi 1 günde silinir (`tarama/portal_depo.py`, günlük bakımda `temizle`). Kullanıcı kendi hesabını silme isteği madde 17'de gelir. Hesapların ayrı bir saklama süresi hukuk onayı ister `[doldurulacak: portal hesabı saklama süresi]`.

Sabit kalanlar: sınır penceresi 30 gün (iş kuralı, `depo.SINIR_GUN`); yönetim oturumu kullanım süresine göre dolar, parola değişince silinir.

Silme günlük bakım işinde (`deploy/bakim.py`) çalışır; yedekten önce yapılır.

## Yedeklerden silme

Silinen veri, silme anından önce alınmış yedeklerde durur. Yedekler 14 adet tutulur (günlük yedekte yaklaşık 14 gün), eski yedekler otomatik silinir. Yani bir kayıt, saklama süresi artı en fazla yaklaşık 14 gün sonra yedeklerden de kaybolur. Bunun müşteriye söylenecek hâli ve yedeklerin uzak kopyası için ayrı süre `[doldurulacak: uzak yedek hedefi ve süresi]` kararı bekliyor. Silme talebi geldiğinde yedeklerdeki kopya için ayrıca işlem yapılmaz; yedeklerin sona ermesi beklenir. Bu, aydınlatma metninde yazılmalıdır.

## Doğrulama

Testler: `tests/test_deploy.py` (`SaklamaTests`). Gerçek sunucuda zamanlanmış bakım çalıştırılmadı; yalnız birim testleri ve geçici dizinde bakım betiği denendi.

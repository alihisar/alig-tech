# alig.tech

Veritabanı yönetim şirketi alig.tech için kurumsal site, demo portalı, sağlık taraması,
yönetim paneli ve yayın hattı. Yalnızca Python standart kütüphanesi, dış kaynak yok.

Bu dosyanın `<!-- oto:... -->` ile işaretli bölümleri `ci/uret_readme.py` tarafından koddan
üretilir. Elle yazılan kısımlar ise açıklamadır; el ile güncellenmesi gerekir.

## Durum

- Ana sayfa: yön C (ajan hizmetini öne çıkarır) varsayılan tema. Logo ve arka plan geçici.
- Portal demosu (`/demo/`), iletişim formu, sağlık taraması (Kip A, PostgreSQL), yönetim paneli (`/yonetim/`) çalışır durumda.
- Yönetim panelinde firma yönetimi var: ad ve e-posta düz metin saklanır, aktif/pasif, not, tarama hakkı sıfırlama, silme.
- Yayın dosyaları (Ansible, nginx, systemd) yazıldı. `yayin.yml`, `geri-al.yml` söz dizimi ve 6 systemd birimi doğrulandı; `site.yml` söz dizimi Ansible koleksiyonu ister, bu ortamda denenemedi. Gerçek sunucuda çalıştırılmadı. Katman katman durum: `docs/canli-kontrol-listesi.md`.
- SQL Server taraması ön sürüm olarak kodlandı, gerçek sunucuda sınanmadı ve varsayılan olarak kapalı.
- Açık işler: firma e-posta doğrulaması (gönderim yöntemi seçilmedi), toplayıcının tüm veritabanlarını dolaşması, SQL Server taramasının gerçek sunucuda sınanması, Kip B'nin açılması (kodlandı, kapalı), isteğe bağlı dil modeli özeti. Sıra ve durum: `docs/yol-haritasi.md`. Kaynak belge: `docs/master-prompt-v2.md`. Mevcut durum dökümü: `docs/faz0-analiz.md`. Son kod incelemesi: `docs/kod-inceleme.md`.

## Yerelde çalıştırma

En kolayı: `python3 yerel.py` (Windows'ta `python yerel.py`). Siteyi derler, `http://localhost:8080/` adresinde açar; form, tarama ve yönetim paneli de bu adreste çalışır.

Elle derleme:

```sh
python3 build/build.py --theme c --out dist/c
python3 -m http.server 8080 --directory dist/c
```

<!-- oto:basla temalar -->
Tasarım temaları: `a`, `b`, `c`. Varsayılan tema `c` (`--theme c`).
<!-- oto:bitis temalar -->

Tarayıcıda `http://localhost:8080/` (Türkçe) ve `/en/` (İngilizce). Hash özetleri için
`localhost` veya HTTPS gerekir (`crypto.subtle`).

## Denetimler

Yerelde ve CI'da aynı komut:

```sh
python3 ci/run_all.py --theme c             # birleştirme isteği
python3 ci/run_all.py --theme c --release   # sürüm etiketi: doldurulacak alan kalmamalı
python3 -m unittest discover -s tests       # yalnızca birim testleri
python3 ci/uret_readme.py                   # README otomatik bölümlerini günceller (run_all de yapar)
```

<!-- oto:basla denetimler -->
`run_all.py` şu 13 denetimi sırayla çalıştırır:

1. derleme
2. toplayici guncel
3. birim testleri
4. html yapisi
5. ic baglantilar
6. dis kaynak
7. boyut butcesi
8. sir taramasi
9. is akisi sabitleme
10. yasakli kaliplar
11. dil esligi
12. doldurulacak alanlar
13. readme guncel
<!-- oto:bitis denetimler -->

<!-- oto:basla testler -->
Birim testleri: 262 test (gerçek PostgreSQL testleri `ALIG_TEST_PG_HOST` olmadan atlanır).
<!-- oto:bitis testler -->

## Dizinler

<!-- oto:basla dizinler -->
| Dizin | İçerik |
| --- | --- |
| `site/` | Kaynak: `i18n/` (TR, EN metinler), `partials/`, `pages/`, `themes/`, `assets/` |
| `build/` | `build.py`, tekrarlanabilir derleme ve SHA-256 manifest |
| `ci/` | Denetim betikleri, `run_all.py`, bu README'nin uretici betigi |
| `tests/` | Birim testleri |
| `docs/` | Tasarim notlari, plan, runbook, DNS, doldurulacak alanlar |
| `form/` | İletişim formu uç noktası (stdlib, SQLite) |
| `tarama/` | Sağlık taraması: toplayıcı şablonları, katalog, kurallar, sunucu, depo; `onsurum/` SQL Server ön sürümü |
| `yonetim/` | Yönetim paneli (TOTP girişli, denetim zincirli) |
| `deploy/` | Paketleme, bakım, duman testi, Ansible |
<!-- oto:bitis dizinler -->

## Rotalar

<!-- oto:basla rotalar -->
| Yol | Kaynak | Açıklama |
| --- | --- | --- |
| `/` | `site` | Statik site (TR), `/en/` İngilizce |
| `/demo/` | `site` | Portal demosu (istemci tarafı, sunucu yok) |
| `/saglik-taramasi/` | `site` | Tarama yükleme sayfası |
| `/tarama-hazirlik/` | `site` | Müşteri hazırlık kılavuzu (tarama hesabı, adımlar) |
| `/api/iletisim` | `form/server.py` | İletişim formu (POST) |
| `/healthz` | `form/server.py` | Form sağlık denetimi |
| `/api/tarama/yukle` | `tarama/server.py` | Tarama dosyası yükleme (POST) |
| `/rapor/<token>/` | `tarama/server.py` | Rapor sayfası (rastgele bağlantı) |
| `/rapor/<token>/sil` | `tarama/server.py` | Raporu hemen silme (POST) |
| `/api/tarama/saglik` | `tarama/server.py` | Tarama sunucu sağlık denetimi |
| `/api/tarama/baglan` | `tarama/server.py` | Doğrudan bağlantı formu ve isteği (varsayılan kapalı) |
| `/api/tarama/baglan/<token>` | `tarama/server.py` | Parolayı alıp taramayı çalıştırma (POST, varsayılan kapalı) |
| `/yonetim/giris` | `yonetim/server.py` | Yönetici girişi (parola + TOTP) |
| `/yonetim/` | `yonetim/server.py` | Özet |
| `/yonetim/firmalar` | `yonetim/server.py` | Firmalar: liste, aktif/pasif |
| `/yonetim/firmalar/<id>` | `yonetim/server.py` | Firma ayrıntısı, not, tarama hakkı, silme |
| `/yonetim/talepler` | `yonetim/server.py` | İletişim talepleri |
| `/yonetim/firmalar.csv` | `yonetim/server.py` | Firma listesi CSV dışa aktarımı |
| `/yonetim/talepler.csv` | `yonetim/server.py` | Talep listesi CSV dışa aktarımı |
| `/yonetim/taramalar` | `yonetim/server.py` | Tarama raporları |
| `/yonetim/denetim` | `yonetim/server.py` | Denetim kaydı ve zincir doğrulaması |
| `/yonetim/sistem` | `yonetim/server.py` | Sistem durumu |
<!-- oto:bitis rotalar -->

## Yeni metin ekleme

Metinler `site/i18n/tr.json` ve `en.json` içinde, aynı anahtarlarla. Şablonda `{{anahtar}}`
kaçışlı, `{{anahtar_html}}` ham yazılır; olmayan anahtar derlemeyi durdurur. Kanıtlanamayan
her iddia yerine `[doldurulacak: ...]` yazılır, güncel liste `docs/doldurulacak.md`.

## Yazı tipleri

Schibsted Grotesk, Source Serif 4 ve Red Hat Mono, SIL OFL 1.1. Dosyalar `site/assets/fonts/`
altında yerel, lisans metinleri yanlarında. Derleme, temanın kullanmadığı yazı tiplerini
çıktıya koymaz.

## Form uç noktası

`form/server.py`: `ALIG_FORM_SALT=... python3 form/server.py --db /var/lib/alig/form.sqlite`.
Ters vekil `/api/iletisim` ve `/healthz` yollarını 127.0.0.1:8090 adresine iletmeli, `X-Real-IP`
başlığını koymalı. Kayıtlar SQLite WAL, zaman UTC, IP tuzlu özet.

## Sağlık taraması

`tarama/` (sunucu, kurallar, depo). Toplayıcı `site/assets/alig-toplayici.py` katalogdan
üretilir: `python3 tarama/uret_toplayici.py` (CI `--kontrol` ile güncelliğini denetler).
Firma adı ve e-posta düz metin saklanır; aydınlatma metni ve saklama süresi için
`docs/doldurulacak.md`. Gerçek PostgreSQL ile sınama:
`ALIG_TEST_PG_HOST=<soket dizini> ALIG_TEST_PG_PORT=<port> ALIG_TEST_PG_USER=<rol> python3 -m unittest tests.test_tarama`.

### SQL Server (ön sürüm)

Katalog, toplayıcı (`tarama/onsurum/alig-toplayici-mssql.py`), kurallar ve testler hazır; gerçek bir SQL Server üzerinde sınanmadı.
Genel sayfada yayımlanmaz, sunucu bu dosyaları yalnızca `ALIG_MSSQL=1` ile kabul eder (`yerel.py` içinde açıktır).
Sınama adımları: `docs/mssql-onsurum.md`.

### Doğrudan bağlantı (Kip B, kapalı)

Müşteri bağlantı bilgisini verir, tarama ayrı bir çalıştırıcı süreçte (`tarama/calistirici.py`) çalışır: `/api/tarama/baglan`. Canlıda yalnızca `dogrudan_baglanti: true` (Ansible) ile açılır ve yalnızca
yönetim panelinden "Doğrudan bağlantı izni" verilen firmalar kullanabilir. Parola saklanmaz. Canlıya almadan önce yapılması
gerekenler: `docs/kip-b-tasarim.md`.

## Yönetim paneli

`yonetim/` (stdlib). Yerelde: `python3 yerel.py`, sonra
`python3 yonetim/kullanici.py --db yerel-yonetim.sqlite ekle ali` ve `http://localhost:8080/yonetim/`.
Doğrulama uygulaması olmadan yerelde denemek için anlık kod:
`python3 yonetim/kullanici.py --db yerel-yonetim.sqlite kod ali`.
Parola ve TOTP ile girilir; her işlem SHA-256 zincirli denetim kaydına yazılır.
Canlı kullanım: `docs/runbook.md`.

## Canlıya alma

`deploy/paketle.py` (tekrarlanabilir paket), `deploy/ansible/` (kurulum, yayın, geri alma),
`deploy/bakim.py` (yedek), `deploy/duman_testi.py`. Adımlar: `docs/runbook.md`, DNS: `docs/dns.md`.

<!-- oto:basla ansible -->
Ansible rolleri: `servisler`, `temel`, `web`, `yayin`.
<!-- oto:bitis ansible -->

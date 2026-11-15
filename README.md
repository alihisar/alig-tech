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
- E-posta doğrulaması kodlandı ve varsayılan olarak kapalı: açmak için SMTP sağlayıcısı ve gönderen adres gerekir (`docs/runbook.md`). Toplayıcı bağlanabildiği tüm veritabanlarını tarar.
- Sağlık taramasında her kural kalıcı kimlikle tek durum üretir (PASS, FAIL, WARNING, UNKNOWN, UNAVAILABLE, NOT_APPLICABLE), veri yokken PASS çıkmaz. Kural listesi: `docs/kural-katalogu.md`.
- Raporda sağlık puanı (0–100), kategori puanları ve kanıt kapsamı birlikte gösterilir; bilinmeyen durum puanı yükseltmez. Yöntem ve varsayılan katsayılar: `docs/kural-katalogu.md`, ayar: `ALIG_PUAN_AYARI` (`docs/runbook.md`).
- Rapor, aynı firmanın aynı sunucudan yaptığı önceki taramayla (saklama süresi dolmadıysa) karşılaştırılır; kaybolan kanıt çözülmüş sayılmaz.
- PostgreSQL taraması yedek (standby) sunucuda da çalışır; tablo istatistiğine ve arşivlemeye dayanan denetimler orada Uygulanmaz. Replikasyon gecikmesi, autovacuum, multixact yaşı, pg_stat_statements ve geçici dosya denetimleri gerçek PostgreSQL 16 birincil ve yedek sunucuda sınandı.
- PostgreSQL 12–18 sürüm ve yetki matrisi: `docs/surum-matrisi.md`. Sorgular gerçek sunucuda yalnız PostgreSQL 16'da sınandı; diğer sürümlerde rapor kanıt güvenini en çok orta gösterir.
- Açık işler: e-posta gönderim yönteminin seçilmesi, SQL Server taramasının gerçek sunucuda sınanması, Kip B'nin açılması (kodlandı, kapalı), isteğe bağlı dil modeli özeti. Sıra ve durum: `docs/yol-haritasi.md`. Kaynak belge: `docs/master-prompt-v2.md`. Mevcut durum dökümü: `docs/faz0-analiz.md`. Son kod incelemesi: `docs/kod-inceleme.md`.

## Yerelde çalıştırma

En kolayı: `python3 yerel.py` (Windows'ta `python yerel.py`). Siteyi derler, `http://localhost:8080/` adresinde açar; form, tarama ve yönetim paneli de bu adreste çalışır.

Elle derleme:

```sh
python3 build/build.py --theme c --out dist/c
python3 -m http.server 8080 --directory dist/c
```

<!-- oto:basla temalar -->
Design themes: `a`, `b`, `c`. Default theme: `c` (`--theme c`).
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
`run_all.py` runs these 15 checks in order:

1. build
2. collector up to date
3. sample report up to date
4. unit tests
5. postgresql tests
6. html structure
7. internal links
8. external resources
9. size budget
10. secret scan
11. workflow pinning
12. banned patterns
13. language parity
14. placeholders
15. readme up to date
<!-- oto:bitis denetimler -->

<!-- oto:basla testler -->
Unit tests: 824 tests (PostgreSQL tests are counted in the separate `postgresql tests` step: an external server if `ALIG_TEST_PG_HOST` is set, otherwise a temporary cluster with the system PostgreSQL 16; if neither exists they are SKIP, and an error in `--release` mode).
<!-- oto:bitis testler -->

## Dizinler

<!-- oto:basla dizinler -->
| Directory | Contents |
| --- | --- |
| `site/` | Source: `i18n/` (TR, EN texts), `partials/`, `pages/`, `themes/`, `assets/` |
| `build/` | `build.py`, reproducible build and SHA-256 manifest |
| `ci/` | Check scripts, `run_all.py`, the generator script for this README |
| `tests/` | Unit tests |
| `docs/` | Design notes, plan, runbook, DNS, fields to be filled in |
| `form/` | Contact form endpoint (stdlib, SQLite) |
| `tarama/` | Health scan (tarama): collector templates, catalog, rules, server, store; `onsurum/` SQL Server preview |
| `yonetim/` | Admin panel (yonetim; TOTP login, audit chain) |
| `deploy/` | Packaging, maintenance, smoke test, Ansible |
<!-- oto:bitis dizinler -->

## Rotalar

<!-- oto:basla rotalar -->
| Path | Source | Description |
| --- | --- | --- |
| `/` | `site` | Static site (TR), `/en/` English |
| `/demo/` | `site` | Portal demo (client side, no server) |
| `/saglik-taramasi/` | `site` | Health scan upload page |
| `/tarama-hazirlik/` | `site` | Customer preparation guide (scan account, steps) |
| `/api/iletisim` | `form/server.py` | Contact form (POST) |
| `/healthz` | `form/server.py` | Form health check |
| `/api/tarama/yukle` | `tarama/server.py` | Scan file upload (POST) |
| `/rapor/<token>/` | `tarama/server.py` | Report page (random link) |
| `/rapor/<token>/sil` | `tarama/server.py` | Delete the report immediately (POST) |
| `/rapor/<token>/dogrula` | `tarama/server.py` | Email verification: opens the report, spends the allowance (POST, off by default) |
| `/api/tarama/saglik` | `tarama/server.py` | Scan server health check |
| `/api/tarama/baglan` | `tarama/server.py` | Direct connection form and request (off by default) |
| `/api/tarama/baglan/<token>` | `tarama/server.py` | Take the password and run the scan (POST, off by default) |
| `/yonetim/giris` | `yonetim/server.py` | Admin login (password + TOTP) |
| `/yonetim/` | `yonetim/server.py` | Summary |
| `/yonetim/firmalar` | `yonetim/server.py` | Companies: list, active/inactive |
| `/yonetim/firmalar/<id>` | `yonetim/server.py` | Company detail, note, scan allowance, deletion |
| `/yonetim/talepler` | `yonetim/server.py` | Contact requests |
| `/yonetim/firmalar.csv` | `yonetim/server.py` | Company list CSV export |
| `/yonetim/talepler.csv` | `yonetim/server.py` | Request list CSV export |
| `/yonetim/taramalar` | `yonetim/server.py` | Scan reports |
| `/yonetim/denetim` | `yonetim/server.py` | Audit log and chain verification |
| `/yonetim/sistem` | `yonetim/server.py` | System status |
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
`docs/doldurulacak.md`. Gerçek PostgreSQL ile sınama: sistem PostgreSQL 16 varsa testler kendi geçici kümesini kurar
(`tests/pg_yardimci.py`); dış sunucu için
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
Ansible roles: `servisler`, `temel`, `web`, `yayin`.
<!-- oto:bitis ansible -->

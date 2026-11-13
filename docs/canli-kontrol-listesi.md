# Canlıya alma kontrol listesi

Her satırın durumu yalnız iki değerden biridir: **DONE** (kanıtı var ve kanıt komutu yazılı) ya da **NOT_TESTED** (denenmedi). Sözdizimi denetimi, kuru çalıştırma ve gerçek dağıtım ayrı katmanlardır: bir katmanın geçmesi öbürünün geçtiği anlamına gelmez.

Bu repoda hiçbir şey gerçek bir sunucuda çalıştırılmadı. Gerçek dağıtım katmanındaki satırlar ilk kurulumdan sonra `python3 deploy/hazirlik.py sunucu` ve elle denetimle doldurulur.

## 1. Sözdizimi ve yapılandırma (bu makinede)

| Madde | Durum | Kanıt ya da eksik |
| --- | --- | --- |
| `yayin.yml` ve `geri-al.yml` söz dizimi | DONE | `python3 deploy/hazirlik.py yerel` |
| `site.yml` söz dizimi | NOT_TESTED | Bu ortamda `community.general` koleksiyonu yok (`ansible-galaxy collection install -r deploy/ansible/requirements.yml` sonrası `hazirlik.py yerel` ile denenir) |
| 6 systemd birimi `systemd-analyze verify` (Kip B birimi dahil) | DONE | `python3 deploy/hazirlik.py yerel`: şablonlar Ansible'ın kendisiyle işlenir; hedefte olmayan yol ve kullanıcı uyarıları dışarıda bırakılır; bozuk ayarlı birimin FAIL verdiği denendi |
| Birimlerde sertleştirme ayarları, yalnız loopback dinleme | DONE | `tests/test_deploy.py` `YapilandirmaTests` |
| Sırların depoda olmadığı | DONE | `tests/test_deploy.py` `test_sirlar_depoda_degil` |
| nginx yapılandırması (`nginx -t`, TLS, yönlendirme, başlıklar, vekil, yükleme sınırı) | DONE | Önceki oturumda gerçek nginx 1.24 ile elle denendi; repoda otomatik test yok |
| Sunucu denetim betiği mantığı (izin, anahtar, disk eşikleri) | DONE | `tests/test_deploy.py` `HazirlikTests` (geçici dizinde; gerçek sunucu kanıtı değil) |
| Yedek betiği disk doluluk koruması | DONE | `tests/test_deploy.py` `BakimDiskTests` |
| Yedekten geri yükleme mantığı | DONE | `tests/test_deploy.py` `GeriYuklemeTests` (geçici dizinde) |
| Toplayıcının tüm veritabanlarını dolaşması | DONE | Yerel PostgreSQL 16 kümesinde: boşluklu adlı veritabanı tarandı, CONNECT yetkisi olmayan "yetki" ile atlandı (`GercekPgTests` ve elle çalıştırma; sunucu değil, müşteri tarafı betik) |
| E-posta gönderimi (SMTP) | NOT_TESTED | Yalnız sahte SMTP nesnesiyle; gerçek sağlayıcı seçilmedi |
| Geçersiz sağlık puanı ayarıyla servislerin başlamaması | DONE | `tests/test_puan.py` `BaslangicTests` (servis süreci değil, `main()` çağrısı; sunucuda systemd ile denenmedi) |

## 2. Kuru çalıştırma (hedef sunucu gerekir)

| Madde | Durum | Kanıt ya da eksik |
| --- | --- | --- |
| `ansible-playbook site.yml --check --diff` | NOT_TESTED | Sunucu yok |
| `ansible-playbook yayin.yml --check --diff` | NOT_TESTED | Sunucu yok |

## 3. Gerçek dağıtım (sunucuda, dağıtımdan sonra)

| Madde | Durum | Kanıt ya da eksik |
| --- | --- | --- |
| Ansible'ın sunucuya uygulanması, ikinci çalıştırmada değişiklik olmaması | NOT_TESTED | |
| Servis kullanıcısı var ve oturum açamaz | NOT_TESTED | `hazirlik.py sunucu` |
| `/etc/alig` 0750, `env` 0640 root:alig-web, veri 0750, yedek 0700 | NOT_TESTED | `hazirlik.py sunucu` |
| `env` içinde tuz ve denetim anahtarı var, en az 32 karakter | NOT_TESTED | `hazirlik.py sunucu` |
| Veritabanı ve yedek dosyaları yalnız sahibine açık | NOT_TESTED | `hazirlik.py sunucu` |
| Disk doluluk (veri ve yedek diskinde %20 üstü boş) | NOT_TESTED | `hazirlik.py sunucu` |
| Servisler ve zamanlayıcılar çalışıyor, form/tarama/yönetim yalnız 127.0.0.1'de | NOT_TESTED | `hazirlik.py sunucu` |
| Birimler sertleştirme ayarlarıyla başlıyor (`SystemCallFilter`, `MemoryDenyWriteExecute`) | NOT_TESTED | `systemd-analyze security alig-form` |
| Duman testi canlı adreste | NOT_TESTED | `deploy/duman_testi.py` |
| certbot ile sertifika ve yenileme | NOT_TESTED | DNS ve sunucu gerekir |
| ufw ve sshd kuralları | NOT_TESTED | Erişimi kesmemek için konsol erişimi hazır olmalı |
| Gerçek sunucuda günlük bakım ve yedek çalıştı | NOT_TESTED | `systemctl start alig-bakim` sonrası günlük |
| Yedekten geri yükleme gerçek sunucuda denendi | NOT_TESTED | `docs/runbook.md` |
| Kip B (yalnız açılacaksa) | NOT_TESTED | `docs/kip-b-tasarim.md` "canlıya almadan önce" |
| E-posta doğrulaması (yalnız açılacaksa): `alig-posta` çalışıyor, ileti ulaşıyor, bağlantı doğruluyor | NOT_TESTED | `docs/runbook.md` "E-posta doğrulaması" |
| Hukuki metinler, gerçek iletişim bilgileri | NOT_TESTED | Ali'den bekliyor |
| Sağlık puanı ayarı (yalnız varsayılan değiştirilecekse): `/etc/alig/puan.json` servis kullanıcısınca okunuyor, panel Sistem sayfası "Bu kurulum için ayarlandı" | NOT_TESTED | `docs/runbook.md` "Sağlık puanı katsayıları" |

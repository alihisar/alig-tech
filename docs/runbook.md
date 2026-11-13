# İşletim el kitabı

Hedef: Ubuntu 24.04 tek sunucu, nginx (TLS), iki Python servisi (`alig-form` 8090, `alig-tarama` 8091, yalnız 127.0.0.1), systemd zamanlayıcıları.

## Ne nerede

| Şey | Yol |
| --- | --- |
| Sürümler | `/srv/alig/releases/<sürüm>`, `current` ve `onceki` bağlantıları |
| Veri (SQLite) | `/var/lib/alig/form.sqlite`, `/var/lib/alig/tarama.sqlite` |
| Yedek | `/var/backups/alig/` (günlük 02:17 UTC, son 14 adet, 0600) |
| Gizli tuz ve denetim anahtarı | `/etc/alig/env` (`ALIG_FORM_SALT`, `ALIG_DENETIM_ANAHTARI`; yalnız root ve servis grubu okur) |
| nginx günlükleri | `/var/log/nginx/alig-*.log` (30 gün; rapor bağlantısı kodu yazılmaz) |

## İlk kurulum

```sh
cd deploy/ansible
ansible-galaxy collection install -r requirements.yml
cp inventory.example.ini inventory.ini           # adresi yazın
# group_vars/all.yml: certbot_eposta, yonetim_kullanici
# Yönetim kullanıcısının ~/.ssh/authorized_keys dosyası dolu olmalı, yoksa SSH sertleştirme durur.
ansible-playbook site.yml --check --diff         # önce kuru çalıştırma
ansible-playbook site.yml
```

## Yayın

```sh
python3 deploy/paketle.py --surum 1.0.0 --release     # doldurulacak alan varsa durur
cd deploy/ansible
ansible-playbook yayin.yml -e surum=1.0.0 -e paket=../../dist/alig-site-1.0.0.tar.gz
```

Akış: paket özeti doğrulanır, açılır, manifest doğrulanır, `current` atomik değişir, servisler yeniden başlar, yerel duman testi (5 deneme) ve alan adı üzerinden `/surum.txt` kontrolü yapılır. Herhangi bir adım başarısız olursa `current` önceki sürüme döner, servisler yeniden başlar, yayın hata ile biter. İlk yayında dönülecek sürüm yoktur; bu durum mesajda yazar.

## Geri alma (elle)

```sh
ansible-playbook geri-al.yml        # "onceki" sürüme döner, duman testi yapar
```

Veritabanı şeması yalnız ileri göçle değişir; sürüm geri alınırken veri geri alınmaz. Şema değiştiren bir sürümden önce yedeği elle alın: `sudo -u alig-web python3 /srv/alig/current/deploy/bakim.py --veri /var/lib/alig --yedek /var/backups/alig`.

## Yedekten geri yükleme

Komut yedeği önce doğrular: SQLite bütünlük denetimi, tablo ve şema sürümü (yedek koddan yeni olamaz), denetim zincirinin sağlamlığı. Doğrulama gerçek dosyaya dokunmaz, geçici kopyada çalışır. `--evet` olmadan hiçbir şey değişmez.

```sh
sudo systemctl stop alig-form alig-tarama alig-yonetim
# 1) kontrol (kuru calistirma); anahtar ve zincir basi varsa verin
sudo -u alig-web bash -c 'set -a; . /etc/alig/env; \
  python3 /srv/alig/current/deploy/bakim.py geri-yukle --veri /var/lib/alig \
  --dosya /var/backups/alig/tarama-<zaman>.sqlite --bas /guvenli/yer/bas.json'
# 2) ayni komut --evet ile gercekten yukler
sudo systemctl start alig-form alig-tarama alig-yonetim
python3 /srv/alig/current/tarama/depo.py dogrula /var/lib/alig/tarama.sqlite   # zincir, anahtarla
```

Davranış:
- Hedef dosyayı (ya da `-wal`, `-shm`) açık tutan başka bir süreç varsa komut durur; önce servisleri durdurun. Denetim `/proc` üzerinden yapılır, bu yüzden komutu servislerle aynı kullanıcıyla (`alig-web`) ya da root ile çalıştırın; başka kullanıcıların süreçleri görülemez.
- Mevcut dosya silinmez, `<ad>.onceki-<zaman>` olarak yanında kalır; sorun çıkarsa geri koyabilirsiniz. Gereksiz olunca elle silin.
- Komutu `alig-web` kullanıcısıyla çalıştırın; root ile çalışırsa dosya sahibi önceki dosyanınki olarak korunur.
- Eski `-wal` ve `-shm` dosyaları kaldırılır, yeni dosya 0600 izinli yazılır, yükleme sonrası bütünlük ve içerik özeti yedekle karşılaştırılır; uyuşmazlıkta önceki dosya geri konur.
- Çıkış kodu: 0 başarılı ya da kuru çalıştırma, 1 doğrulama ya da yükleme hatası (hiçbir şey değişmedi), 2 kullanım hatası.
- Anahtarlı kayıtlar anahtar olmadan doğrulanamaz ve uyarı verilir; yanlış anahtarda yedek reddedilir. Zincir başı verilmezse baştan üretilmiş ya da son kayıtları kesilmiş yedek yakalanamaz, komut bunu uyarı olarak yazar.
- Geri yükleme yedeğin alındığı andan sonraki kayıtları (rapor, talep, denetim) geri getirmez.

Yedek, sunucuyla aynı diskte durur: sunucu kaybına karşı koruma sağlamaz. Yedek dizinini düzenli olarak başka bir yere kopyalayın `[doldurulacak: uzak yedek hedefi]`. Sunucu kaybında boş bir veri dizinine de yüklenebilir (hedef dosya yoksa doğrudan yazılır).

**Durum:** birim testleri geçici dizinde geri yüklemeyi dener (bozulma, kesilmiş zincir, yanlış anahtar, kullanımdaki hedef). Gerçek sunucuda, systemd servisleri durdurulup başlatılarak henüz denenmedi.

### Denetim zinciri: anahtar ve zincir başı

Kayıtların `alanlar` sütunu (firma, hedef, sonuç, neden, IP özeti) özete dahildir; değiştirilirse zincir kırılır. Yönetici yeni bir IP'den girince denetime "yeni IP'den giriş yapıldı" yazılır (kullanıcının ilk girişi uyarı sayılmaz). IP'ler düz yazılmaz: 16 karakterlik özet olarak tutulur, denetim anahtarı varsa HMAC ile.

Yeni denetim kayıtları `ALIG_DENETIM_ANAHTARI` ile HMAC-SHA-256 olarak yazılır; anahtar yoksa eski SHA-256 biçimi kullanılır. Eski kayıtlar bozulmaz. Anahtarlı kayıtlardan sonra anahtarsız kayıt gelirse zincir kırık sayılır. Anahtar en az 32 karakter olmalı, kısa anahtarla servisler başlamaz.

Doğrulama anahtarı ortamdan okur: `sudo bash -c 'set -a; . /etc/alig/env; python3 /srv/alig/current/tarama/depo.py dogrula /var/lib/alig/tarama.sqlite'`. Anahtar olmadan çalıştırılırsa bağlantı denetlenir, HMAC denetlenemez ve komut 1 döner.

Anahtar ve veritabanı aynı sunucuda durduğu sürece, sunucuya tam erişen biri zinciri yeniden üretebilir. Bunu yakalamak için zincir başını düzenli olarak sunucu dışına yazın: `python3 /srv/alig/current/tarama/depo.py bas /var/lib/alig/tarama.sqlite > bas.json`. Sonradan `dogrula <db> --bas bas.json` ile kontrol edilir; zincir başı değişmişse ya da son kayıtlar kesilmişse zincir kırık çıkar. Zincir başının nereye gideceği `[doldurulacak: zincir başı hedefi]` olarak açık duruyor. Anahtarı yedeklerden ayrı saklayın; anahtar kaybolursa eski anahtarlı kayıtlar doğrulanamaz.

Yedek, sunucuyla aynı diskte durur: sunucu kaybına karşı koruma sağlamaz. Yedek dizinini düzenli olarak başka bir yere kopyalayın `[doldurulacak: uzak yedek hedefi]`.

## İzleme

`alig-izleme.timer` 5 dakikada bir duman testini çalıştırır (`http://127.0.0.1:8081`). Başarısızlıkta `alig-uyari.service` sistem günlüğüne kritik kayıt yazar. Bildirim yolu (e-posta ya da mesaj) `[doldurulacak: bildirim yöntemi]`; `/etc/systemd/system/alig-uyari.service` içindeki `ExecStart` değiştirilerek bağlanır.

```sh
systemctl list-timers 'alig-*'
journalctl -u alig-izleme -n 50
journalctl -u alig-form -u alig-tarama -n 100
```

## Yönetim paneli

Servis `alig-yonetim` yalnız `127.0.0.1:8092` üzerinde dinler. İki erişim yolu var (`group_vars/all.yml`, `yonetim_izinli_ipler`):

- **Boş (varsayılan):** Panel internete açılmaz, nginx `/yonetim` için 404 döner. Erişim SSH tüneliyle: `ssh -L 8092:127.0.0.1:8092 deploy@sunucu`, sonra tarayıcıda `http://localhost:8092/yonetim/`. Stil ve logo dosyalarını panel servisi kendisi sunar.
- **IP listesi dolu:** nginx yalnız o adreslere `https://alig.tech/yonetim/` yolunu açar, diğerlerine 403 döner. Ofis ya da VPN çıkış adresinizi yazın.

Kullanıcı yönetimi sunucuda, servis kullanıcısıyla:

```sh
sudo -u alig-web python3 /srv/alig/current/yonetim/kullanici.py --db /var/lib/alig/yonetim.sqlite ekle ali
#   parola sorar (en az 12 karakter), doğrulama uygulaması için anahtarı bir kez gösterir
sudo -u alig-web python3 /srv/alig/current/yonetim/kullanici.py --db /var/lib/alig/yonetim.sqlite liste
... parola ali | totp-yenile ali | sil ali      # parola ve anahtar değişince açık oturumlar kapanır
```

Giriş: kullanıcı adı, parola ve 6 haneli doğrulama kodu. 15 dakikada 5 hatalı denemeden sonra kullanıcı, 10 denemeden sonra IP adresi 15 dakika engellenir. Oturum 30 dakika boşta kalınca ya da 8 saat sonra kapanır. Telefon kaybolursa `totp-yenile` ile yeni anahtar üretin.

Firmalar sayfası, sağlık taraması yükleyen ve iletişim formu dolduran şirketleri tek listede gösterir. Düğmeler: Pasif et / Aktif et (pasif firma yeni tarama yükleyemez, mevcut raporları durur), Tarama hakkını sıfırla (30 günlük sayımı siler), Not, Kalıcı olarak sil (firma kaydı ve raporları; iletişim talepleri kalır).

Paneldeki her işlem (giriş, talep ve rapor görüntüleme, durum değişikliği, silme) yönetim denetim zincirine yazılır; müşteri raporuna erişim ayrıca tarama zincirine `yonetici:<ad>` olarak düşer. `yonetim.sqlite` doğrulama anahtarlarını içerir: yedekleri bu yüzden 0600 izinlidir, başka yere kopyalarken şifreleyin.

## Sorun giderme

| Belirti | Bak |
| --- | --- |
| Siteye ulaşılamıyor | `systemctl status nginx`, `nginx -t`, `ufw status` |
| Form ya da yükleme 502 | `systemctl status alig-form alig-tarama`, port dinleniyor mu: `ss -ltnp \| grep -E '8090\|8091'` |
| Yükleme 413 | Dosya 5 MB üstü ya da nginx `client_max_body_size 6m` sınırı |
| Yükleme 429 | Şirket sınırı (30 günde 2) ya da hız sınırı. Sınır verisi `kullanim` tablosunda, düz adres tutulmaz |
| Sertifika yenilenmedi | `certbot renew --dry-run`, `systemctl list-timers certbot*` |

## Gizli tuzu değiştirme

`/etc/alig/env` dosyasını silip `site.yml` çalıştırmak yeni tuz üretir. Tuz yalnız form kayıtlarındaki IP özetlerini etkiler; eski özetler yeni kayıtlarla eşleşmez, bu kabul edilebilir.

## Bu repoda neyin sınandığı

Katman katman durum: `docs/canli-kontrol-listesi.md` (DONE ya da NOT_TESTED). Dağıtımdan sonra: `python3 /srv/alig/current/deploy/hazirlik.py sunucu` (kullanıcılar, izinler, anahtarlar, disk, servisler, portlar; sır değerlerini yazdırmaz, FAIL varsa 1 döner).

Sınandı: paket tekrarlanabilirliği, bakım ve yedek betiği, duman testi, nginx yapılandırması (`nginx -t` ve gerçek nginx 1.24 ile uçtan uca: TLS, yönlendirme, başlıklar, vekil, yükleme sınırı, günlükte kod gizleme), `current` bağlantısı değiştirme mantığı, Ansible söz dizimi ve lint.

Sınanmadı (gerçek sunucuda ilk çalıştırmada izleyin): Ansible'ın gerçek bir sunucuya uygulanması, ufw ve sshd kuralları, certbot ile sertifika alma, systemd birimlerinin sertleştirme ayarlarıyla başlaması (`SystemCallFilter`, `MemoryDenyWriteExecute`). Bir birim başlamazsa önce `journalctl -u alig-form` ve `systemd-analyze security alig-form` bakın, ayarı gevşetmek yerine nedenini bulun.

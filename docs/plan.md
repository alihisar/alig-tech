# Uygulama planı

Durum: `[x]` bitti ve doğrulandı, `[ ]` bekliyor.

1. [x] Depo iskeleti, `.gitignore`, `config.example`, `CHANGELOG.md`
2. [x] Derleme betiği (TR/EN, tekrarlanabilir, manifest, yazı tipi ayıklama)
3. [x] CI denetimleri ve `run_all.py`, GitHub Actions tanımı (SHA'ya sabit)
4. [x] Ana sayfa taslağı, iki yön (A Konsol, B Rapor), hero'da çalışan failover konsolu
5. [x] Yön seçimi: C (Ajan). Logo ve arkaplan geçici, bkz. `site/assets/bg/README.md`
6. [ ] Seçilen yönün karşı teması (açık/koyu), ayrıca tasarlanır
7. [ ] Diğer sayfalar: Hizmetler, Nasıl çalışır, Güvenlik, Hakkımızda, Yazılar (2 taslak)
8. [x] Portal demosu (`/demo`): filo, bulgular, onay kuyruğu, olay zaman çizelgesi, sertleştirme skoru, denetim kaydı (tarayıcıda SHA-256 doğrulama), raporlar
9. [x] Form uç noktası (`form/`): stdlib, SQLite WAL, doğrulama, hız sınırı, bal küpü, `/healthz`, testler
10. [x] Paketleme: `alig-site-<sürüm>.tar.gz` ve manifest
11. [x] Ansible (`deploy/`): ters vekil + TLS, güvenlik duvarı, SSH sertleştirme, otomatik güvenlik güncellemesi, form servisi (sandbox'lı systemd)
12. [x] Dağıtım ve geri alma: `releases/<sürüm>`, `current` bağı, duman testi, otomatik geri alma
13. [x] İzleme, kayıt saklama (varsayılan 30 gün), SQLite yedeği ve geri yükleme betiği
14. [x] Runbook ve `docs/dns.md`

Her adım, doğrulaması geçmeden sonrakine geçmez.

## Sağlık taraması (docs/saglik-taramasi-tasarim.md)

1. [x] Tasarım ve tehdit modeli
2. [x] Katalog, kurallar, toplayıcı, depo, yükleme doğrulaması, rapor, sunucu, sayfa (Kip A, PostgreSQL)
3. [x] Şirket başına sınır (alan adı ya da ücretsiz posta adresi başına 30 günde 2). E-posta doğrulaması gönderim yöntemi gelince
4. [ ] SQL Server kataloğu
5. [ ] Kip B (doğrudan bağlantı): önce tehdit modeline SSRF, rol sahipliği ve kimlik bilgisi saklama eklenir
6. [ ] İsteğe bağlı dil modeli özeti

## Yönetim paneli

1. [x] Giriş (parola + doğrulama kodu), oturum, CSRF, giriş sınırı, kullanıcı CLI
2. [x] Özet, talepler, taramalar ve rapor, denetim kaydı, sistem
3. [x] Yerel çalıştırma, paket, systemd, nginx (IP listesi ya da SSH tüneli), runbook
4. [x] Firmalar: kayıt, aktif/pasif, tarama hakkı sıfırlama, not, silme
5. [ ] İstenirse: talep dışa aktarma (CSV), bildirim, birden çok rol

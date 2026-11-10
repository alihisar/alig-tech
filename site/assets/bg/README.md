# Arkaplanlar (geçici)

Şimdilik düz renk yer tutucular. Kalıcı görseli aynı dosya adıyla bu klasöre koyun,
CSS'e dokunmak gerekmez (`site/themes/c/style.css`, `--bg-hero-image`).

- `hero.svg`: üst çubuk ve hero arkası. Metin beyaz olduğundan görsel koyu kalmalı (kontrast en az 4,5:1).
- Logo: `site/assets/logo.svg` (beyaz, koyu zemin için). Üst çubukta 28 px yükseklikte görünür.

Sonra ekle: görsel eklendiğinde `python3 ci/run_all.py --theme c` boyut bütçesini (300 KB) denetler.

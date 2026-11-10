# DNS ve sertifika

Sertifika alınmadan önce DNS kayıtları yayılmış olmalı; `site.yml` içindeki certbot adımı Let's Encrypt'in HTTP doğrulamasını kullanır.

| Ad | Tür | Değer | Not |
| --- | --- | --- | --- |
| `alig.tech` | A | sunucunun IPv4 adresi | Sunucu IPv6 alıyorsa AAAA da ekleyin. Eklerseniz sunucu IPv6 üzerinden de çalışmalıdır. |
| `www.alig.tech` | CNAME | `alig.tech.` | nginx www'yi kök alana 308 ile yönlendirir. |
| `alig.tech` | CAA | `0 issue "letsencrypt.org"` | Yalnızca Let's Encrypt sertifika verebilsin. |

TTL: kurulumdan önce 300 sn yapın, her şey oturunca 3600 sn.

## E-posta için (iletişim e-postası belli olunca)

SPF, DKIM ve DMARC kayıtları e-posta sağlayıcısına göre değişir. `[doldurulacak: e-posta sağlayıcısı]`. Önerilen en az: `_dmarc.alig.tech TXT "v=DMARC1; p=none; rua=mailto:..."` ile başlayıp raporlara bakarak `quarantine` ve `reject` düzeyine çıkmak.

## Sırayla

1. Sunucuyu kurun, `inventory.ini` içine adresini yazın.
2. A ve CNAME kayıtlarını ekleyin, `dig +short alig.tech` doğru adresi dönene kadar bekleyin.
3. `site.yml` çalıştırın (sertifikayı alır, HTTPS'i açar).
4. İlk sürümü yayınlayın (`docs/runbook.md`).
5. HSTS 1 yıl yayımlanır. Sertifika ya da HTTPS sorunu çıkarsa tarayıcılar HTTP'ye düşmez: ilk haftalarda `hsts_saniye` değerini 300 yaparak başlayıp sonra artırabilirsiniz (`group_vars/all.yml`).

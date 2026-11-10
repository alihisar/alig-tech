# alig.tech tasarım notları

## Referanslar (yalnızca ilke; hiçbir şey kopyalanmadı)

Üç site incelendi. Not: sayfalar araçla işaretleme düzeyinde okundu, tarayıcıda
render edilmiş hâli görülmedi; renk ve boşluk çıkarımları kesin değil.

| Site | Alınan ilke |
| --- | --- |
| Tailscale | Hero seyrek, gezinme ve alt bilgi yoğun. Tek doygun vurgu rengi, geri kalanı nötr. |
| Linear | Pazarlama metni seyrek, ürün görüntüsü yoğun; yoğunluk bilinçli değişiyor. Vurgu rengi yalnızca durum göstergelerinde. |
| PostgreSQL | İçerik aciliyet sırasıyla dizili, tarihler ve sürümler tek satırda, süs yok. Güveni sadelik veriyor. |

Çıkan sonuç: ürünü hemen göster (hero'da çalışan bir konsol), yoğunluğu
yukarıdan aşağı artır, vurgu rengini anlama bağla.

## Tasarım planı (kodlamadan önce yazıldı, sonra gözden geçirildi)

### İlk taslakta fark edilen ve değiştirilen varsayılanlar

| İlk akla gelen | Neden değişti | Yerine |
| --- | --- | --- |
| Açık yön: krem zemin, yüksek kontrastlı serif, toprak rengi vurgu | Üretilmiş sitelerde en sık görülen kalıp | Soğuk beyaz zemin, lacivert mürekkep, vurgu yalnızca "insan onayı" anlamında |
| Koyu yön: siyaha yakın zemin, tek parlak yeşil vurgu | Aynı şekilde kalıp | Lacivert-arduvaz zemin, aynı anlamsal kehribar |
| Hero: büyük rakam + gradyan | Konuya özgü değil | Çalışan örnek küme: lideri durdur, ajanın bulgusunu ve hash zincirli kaydı izle |
| Üç eşit kart ızgarası | Her içeriği aynı kalıba sokuyor | Satır ve tablolar; içerik neyse biçim o |
| Küçük harfli etiket üstte, nokta ile ayrılmış meta, ok işareti | Şablon kalıbı | Kullanılmadı |
| Her etikette monospace | Şablon kalıbı | Monospace yalnızca gerçek terminal çıktısında |

### Ortak ilkeler

- Kehribar (#f2b441) tek vurgu ve tek anlamı var: bir insanın karar vermesi
  gerekiyor (onay düğmesi, akıştaki onay adımı, CTA). Başka yerde kullanılmaz.
- Durum renkleri (yeşil/kırmızı) yalnızca konsol çıktısında, anlam taşıdığı yerde.
- Bu sayfanın akılda kalacak tek öğesi hero konsolu. Geri kalanı sakin.
- Hareket yalnızca kullanıcının eylemine yanıt: lideri durdurunca olay akışı
  sırayla belirir. Kaydırınca beliren animasyon yok. `prefers-reduced-motion`
  açıkken akış anında tamamlanır.
- Gradyan, cam efekti, bulanıklık, gölge, emoji, büyük harf dönüşümü yok
  (`ci/check_banned.py` bunları denetler).
- Metin: ilk çoğul kişi, somut, kısa.

### Yön A: Konsol (koyu)

- Renk: zemin #1b2433, yüzey #243044, çizgi #3a4a63, metin #e4e9f1,
  ikincil metin #9aa8bf, vurgu #f2b441.
- Yazı: Schibsted Grotesk (başlık ve gövde, tek aile), Red Hat Mono (yalnızca konsol).
- Yerleşim: sola hizalı; hero'da metin solda, konsol sağda (5/7). Bölüm
  başlıkları içeriğin üstünde. Hizmetler ve kademeler tablo satırı.
- Köşe: 4 px düğme ve alan, 8 px konsol. Gölge yok.

### Yön B: Rapor (açık)

- Renk: zemin #ffffff, mürekkep #16233b (lacivert), ikincil #4d5b73,
  çizgi #cfd6e0, vurgu #f2b441 (zemin olarak, lacivert metinle).
- Yazı: Source Serif 4 (başlık ve gövde), Red Hat Mono (yalnızca konsol).
- Yerleşim: denetim raporu düzeni. Başlık tam genişlikte üstte, konsol altında
  tam genişlikte bir "şekil". Bölüm başlıkları sol kenar sütununda (yapışkan),
  içerik sağda. Bağlantılar lacivert, kehribar alt çizgili.
- Köşe: yok, 1 px çizgi.

## Logo ve favicon

- Yazı logosu: "alig.tech", yönün kendi yazı tipiyle, tek ağırlık.
- Favicon 1 (`site/assets/favicon.svg`): bir lider, iki yedek (küme).
- Favicon 2 (`site/assets/favicon-alt.svg`): üç log satırı, ilki kehribar.

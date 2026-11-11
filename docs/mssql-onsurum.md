# SQL Server sağlık taraması (ön sürüm)

Durum: kod ve testler hazır, **gerçek bir SQL Server üzerinde sınanmadı**. Bu yüzden genel sayfada yayımlanmaz ve sunucu bu dosyaları yalnızca açıkça etkinleştirilirse kabul eder.

## Neler var

| Parça | Yer |
| --- | --- |
| Sorgu kataloğu (14 denetim, yalnızca `SELECT`) | `tarama/katalog.py` içinde `MSSQL` |
| Toplayıcı betik (`sqlcmd` kullanır) | `tarama/onsurum/alig-toplayici-mssql.py` (şablon: `tarama/toplayici/sablon_mssql.py`) |
| Çalışan sorguların listesi | `tarama/onsurum/sorgu-katalogu-mssql.txt` |
| Tarama girişi açma ve kaldırma | `tarama/onsurum/alig-giris-mssql.sql`, `alig-giris-mssql-kaldir.sql` |
| Kurallar ve bulgu metinleri (TR, EN) | `tarama/kurallar_mssql.py` |
| Testler (sahte `sqlcmd` ile) | `tests/test_mssql.py` |

## Gereksinimler

- SQL Server 2016 ya da üstü (`FOR JSON` gerekir).
- `sqlcmd` istemcisi ve Python 3.9 ya da üstü.
- Yalnızca `VIEW SERVER STATE` ve `VIEW ANY DEFINITION` yetkili `alig_hc` girişi. Hiçbir veritabanında kullanıcı açılmaz.

## Gerçek sunucuda sınama adımları

1. Girişi açın (parola ortam değişkeninden okunur, komut satırına yazılmaz):
   `export ALIG_PAROLA='...' ; sqlcmd -S <sunucu> -E -i tarama/onsurum/alig-giris-mssql.sql`
2. Betiği çalıştırın:
   `SQLCMDPASSWORD='...' python3 tarama/onsurum/alig-toplayici-mssql.py --sunucu <sunucu>,1433 --kullanici alig_hc --sifrele --maskele`
3. Ekrandaki listede her denetimin `ok` ya da `ATLANDI (neden)` olduğuna bakın. `ATLANDI (desteklenmiyor)` ya da `ATLANDI (hata)` görülen her denetim bir düzeltme adayıdır.
4. `alig-toplama-mssql.json` dosyasını açıp değerlerin sunucudaki gerçek durumla uyuştuğunu denetleyin.
5. Yerelde `python3 yerel.py` çalıştırıp dosyayı tarama sayfasından yükleyin (yerelde SQL Server açıktır) ve raporu okuyun.
6. Girişi kaldırın: `sqlcmd -S <sunucu> -E -i tarama/onsurum/alig-giris-mssql-kaldir.sql`

## Sınanması gereken belirsizlikler

- `sqlcmd` çıktısı: betik `-y 0` kullanır ve çıktıda ilk `[` ile son `]` arasını JSON sayar. ODBC tabanlı `sqlcmd` ile yeni `go-sqlcmd` aynı davranmayabilir.
- `msdb.dbo.backupset` okuması: giriş `msdb` içinde yalnızca `guest` üzerinden okur. Sıkılaştırılmış sunucularda `yetki` hatası verebilir.
- Yedek başka bir replikada alınıyorsa `ms_yedek` yanlış alarm üretir.
- `LastGoodCheckDbTime` özelliği olmayan yapılarda `ms_checkdb` boş döner ve bulgu üretmez.
- `ms_sifreleme` yalnızca tarama anındaki TCP bağlantılarına bakar.
- Azure SQL Database ve Managed Instance için sürüm kuralı atlanır; diğer denetimler bu ortamlarda denenmedi.

## Canlıda açma

Sınama tamamlanınca: tarama servisinde `ALIG_MSSQL=1` ortam değişkeni, ardından betiğin ve giriş dosyalarının `site/assets` altına taşınması, tarama ve hazırlık sayfalarına SQL Server adımlarının eklenmesi. Bunlar bilerek yapılmadı.

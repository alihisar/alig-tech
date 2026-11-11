-- alig.tech sağlık taraması (SQL Server, ön sürüm): salt okunur tarama girişi
-- Çalıştırma (parola komut satırına yazılmaz, ortam değişkeninden okunur):
--   Linux/macOS : export ALIG_PAROLA='...' ; sqlcmd -S <sunucu> -E -i alig-giris-mssql.sql
--   PowerShell  : $env:ALIG_PAROLA='...' ; sqlcmd -S <sunucu> -E -i alig-giris-mssql.sql
-- Gereken yetki: giriş oluşturabilen bir hesap (securityadmin ya da sysadmin).
-- Bu dosya veri değiştirmez; yalnızca aşağıdaki girişi oluşturur.

:on error exit
USE master;
CREATE LOGIN alig_hc WITH PASSWORD = N'$(ALIG_PAROLA)', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF, DEFAULT_DATABASE = master;
-- Yalnızca iki yetki: sunucu durum görünümlerini ve nesne tanımlarını okuma.
GRANT VIEW SERVER STATE TO alig_hc;
GRANT VIEW ANY DEFINITION TO alig_hc;
-- Hiçbir veritabanında kullanıcı açılmaz, hiçbir tabloya okuma yetkisi verilmez.

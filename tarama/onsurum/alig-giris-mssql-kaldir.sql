-- alig.tech sağlık taraması (SQL Server, ön sürüm): tarama girişini kaldırma
--   sqlcmd -S <sunucu> -E -i alig-giris-mssql-kaldir.sql
:on error exit
USE master;
IF EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'alig_hc') DROP LOGIN alig_hc;

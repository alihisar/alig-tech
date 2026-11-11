#!/usr/bin/env python3
"""alig.tech saglik taramasi toplayicisi, SQL Server (ON SURUM). Yalnizca standart kutuphane, Python 3.9+.

Musterinin kendi agi icinde calisir, AGA HICBIR SEY GONDERMEZ. Sabit, yalnizca SELECT iceren
sorgu katalogunu `sqlcmd` ile calistirir ve tek bir JSON dosyasi yazar. SQL Server 2016 ve ustu.

Kullanim:
  python3 alig-toplayici-mssql.py --sunucu sql.ornek.local,1433 --kullanici alig_hc --sifrele --maskele
  python3 alig-toplayici-mssql.py --sunucu sql.ornek.local --windows --maskele
Parola: SQLCMDPASSWORD ortam degiskeni. Komut satirindan parola kabul edilmez.
Calisan sorgularin tam listesi: sorgu-katalogu-mssql.txt
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

KATALOG = json.loads(r'''{"format": "alig-toplayici/1", "kontroller": [{"id": "ms_surum", "kolonlar": ["ana_surum", "surum", "motor_turu"], "maske": [], "sql": "SELECT CAST(SERVERPROPERTY('ProductMajorVersion') AS int) AS ana_surum, CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(40)) AS surum, CAST(SERVERPROPERTY('EngineEdition') AS int) AS motor_turu"}, {"id": "ms_yedek", "kolonlar": ["veritabani", "kurtarma_modeli", "tam_saat", "log_saat"], "maske": ["veritabani"], "sql": "SELECT d.name AS veritabani, d.recovery_model_desc AS kurtarma_modeli, DATEDIFF(hour, MAX(CASE WHEN b.type = 'D' THEN b.backup_finish_date END), GETDATE()) AS tam_saat, DATEDIFF(hour, MAX(CASE WHEN b.type = 'L' THEN b.backup_finish_date END), GETDATE()) AS log_saat FROM sys.databases d LEFT JOIN msdb.dbo.backupset b ON b.database_name = d.name WHERE d.database_id NOT IN (2, 3) AND d.state = 0 AND d.source_database_id IS NULL GROUP BY d.name, d.recovery_model_desc"}, {"id": "ms_checkdb", "kolonlar": ["veritabani", "gun"], "maske": ["veritabani"], "sql": "SELECT d.name AS veritabani, DATEDIFF(day, CAST(DATABASEPROPERTYEX(d.name, 'LastGoodCheckDbTime') AS datetime), GETDATE()) AS gun FROM sys.databases d WHERE d.database_id <> 2 AND d.state = 0"}, {"id": "ms_db_ayar", "kolonlar": ["veritabani", "kimlik", "auto_shrink", "auto_close", "sayfa_dogrulama", "durum", "trustworthy"], "maske": ["veritabani"], "sql": "SELECT name AS veritabani, database_id AS kimlik, CAST(is_auto_shrink_on AS int) AS auto_shrink, CAST(is_auto_close_on AS int) AS auto_close, page_verify_option_desc AS sayfa_dogrulama, state_desc AS durum, CAST(is_trustworthy_on AS int) AS trustworthy FROM sys.databases WHERE database_id <> 2"}, {"id": "ms_sunucu_ayar", "kolonlar": ["ad", "deger"], "maske": [], "sql": "SELECT name AS ad, CAST(value_in_use AS bigint) AS deger FROM sys.configurations WHERE name IN ('max server memory (MB)', 'max degree of parallelism', 'cost threshold for parallelism', 'xp_cmdshell', 'Ad Hoc Distributed Queries', 'cross db ownership chaining', 'remote admin connections', 'backup compression default', 'clr enabled')"}, {"id": "ms_sa", "kolonlar": ["devre_disi", "adi_sa"], "maske": [], "sql": "SELECT CAST(is_disabled AS int) AS devre_disi, CASE WHEN name = 'sa' THEN 1 ELSE 0 END AS adi_sa FROM sys.sql_logins WHERE sid = 0x01"}, {"id": "ms_sysadmin", "kolonlar": ["giris", "tur", "devre_disi"], "maske": ["giris"], "sql": "SELECT TOP 50 p.name AS giris, p.type_desc AS tur, CAST(p.is_disabled AS int) AS devre_disi FROM sys.server_role_members m JOIN sys.server_principals r ON r.principal_id = m.role_principal_id JOIN sys.server_principals p ON p.principal_id = m.member_principal_id WHERE r.name = 'sysadmin'"}, {"id": "ms_parola_politikasi", "kolonlar": ["sayi"], "maske": [], "sql": "SELECT COUNT(*) AS sayi FROM sys.sql_logins WHERE is_policy_checked = 0 AND is_disabled = 0 AND name NOT LIKE '##%'"}, {"id": "ms_tempdb", "kolonlar": ["veri_dosyasi", "cpu"], "maske": [], "sql": "SELECT (SELECT COUNT(*) FROM tempdb.sys.database_files WHERE type = 0) AS veri_dosyasi, (SELECT cpu_count FROM sys.dm_os_sys_info) AS cpu"}, {"id": "ms_ag", "kolonlar": ["grup", "replika", "saglik", "rol", "baglanti"], "maske": ["grup", "replika"], "sql": "SELECT TOP 50 ag.name AS grup, ar.replica_server_name AS replika, rs.synchronization_health_desc AS saglik, rs.role_desc AS rol, rs.connected_state_desc AS baglanti FROM sys.dm_hadr_availability_replica_states rs JOIN sys.availability_replicas ar ON ar.replica_id = rs.replica_id JOIN sys.availability_groups ag ON ag.group_id = rs.group_id"}, {"id": "ms_dosya_buyume", "kolonlar": ["veritabani", "dosya", "tur"], "maske": ["veritabani", "dosya"], "sql": "SELECT TOP 50 DB_NAME(database_id) AS veritabani, name AS dosya, type_desc AS tur FROM sys.master_files WHERE is_percent_growth = 1 AND database_id <> 2"}, {"id": "ms_sifreleme", "kolonlar": ["toplam", "sifreli"], "maske": [], "sql": "SELECT COUNT(*) AS toplam, ISNULL(SUM(CASE WHEN encrypt_option = 'TRUE' THEN 1 ELSE 0 END), 0) AS sifreli FROM sys.dm_exec_connections WHERE net_transport = 'TCP'"}, {"id": "ms_acik_islem", "kolonlar": ["giris", "sure_sn"], "maske": ["giris"], "sql": "SELECT TOP 20 s.login_name AS giris, DATEDIFF(second, t.transaction_begin_time, GETDATE()) AS sure_sn FROM sys.dm_tran_session_transactions st JOIN sys.dm_tran_active_transactions t ON t.transaction_id = st.transaction_id JOIN sys.dm_exec_sessions s ON s.session_id = st.session_id WHERE s.is_user_process = 1 ORDER BY 2 DESC"}, {"id": "ms_kimlik", "kolonlar": ["yalniz_windows"], "maske": [], "sql": "SELECT CAST(SERVERPROPERTY('IsIntegratedSecurityOnly') AS int) AS yalniz_windows"}], "motor": "mssql"}''')
FORMAT = KATALOG["format"]
KATALOG_OZETI = hashlib.sha256(json.dumps(KATALOG["kontroller"], sort_keys=True).encode()).hexdigest()

ON_EK = ("SET NOCOUNT ON; SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED; SET LOCK_TIMEOUT 2000; "
         "SET DEADLOCK_PRIORITY LOW; DECLARE @j nvarchar(max) = (")
SON_EK = " FOR JSON PATH, INCLUDE_NULL_VALUES); SELECT ISNULL(@j, N'[]');"


def hata_sinifi(metin):
    s = (metin or "").lower()
    if "permission" in s or "denied" in s or "not have permission" in s:
        return "yetki"
    if "timeout expired" in s or "lock request time out" in s:
        return "zaman_asimi"
    if "invalid object name" in s or "invalid column name" in s or "incorrect syntax" in s or "not a recognized" in s:
        return "desteklenmiyor"
    return "hata"


def json_ayikla(cikti):
    """sqlcmd ciktisinda baslik ya da bos satir olabilir: ilk '[' ile son ']' arasini alir."""
    a, b = cikti.find("["), cikti.rfind("]")
    if a < 0 or b < a:
        raise ValueError("json yok")
    veri = json.loads(cikti[a:b + 1].replace("\r", "").replace("\n", ""))
    if not isinstance(veri, list):
        raise ValueError("liste degil")
    return veri


def calistir(sqlcmd, baglanti, sql):
    cmd = [sqlcmd] + baglanti + ["-b", "-l", "15", "-t", "15", "-y", "0", "-Q", ON_EK + sql + SON_EK]
    env = dict(os.environ)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45, env=env)
    except subprocess.TimeoutExpired:
        return {"durum": "hata", "neden": "zaman_asimi"}
    except FileNotFoundError:
        raise SystemExit("sqlcmd bulunamadi: --sqlcmd ile yolunu verin")
    if r.returncode != 0:
        return {"durum": "hata", "neden": hata_sinifi(r.stdout + r.stderr)}
    try:
        return {"durum": "ok", "satirlar": json_ayikla(r.stdout)}
    except ValueError:
        return {"durum": "hata", "neden": hata_sinifi(r.stdout + r.stderr)}


class Maske:
    def __init__(self):
        self.harita = {}

    def al(self, kolon, deger):
        if deger is None or not isinstance(deger, str):
            return deger
        return self.harita.setdefault(deger, "nesne-%d" % (len(self.harita) + 1))


def main(argv=None):
    ap = argparse.ArgumentParser(description="alig.tech saglik taramasi toplayicisi, SQL Server (on surum, yalnizca SELECT)")
    ap.add_argument("--sunucu", required=True, help="sunucu[,port] ya da sunucu\\ornek")
    ap.add_argument("--kullanici", help="SQL girisi; parola SQLCMDPASSWORD ortam degiskeninden okunur")
    ap.add_argument("--windows", action="store_true", help="Windows kimlik dogrulamasi (-E)")
    ap.add_argument("--sifrele", action="store_true", help="baglantiyi sifrele (-N)")
    ap.add_argument("--sertifikaya-guven", action="store_true", help="sunucu sertifikasini dogrulamadan kabul et (-C)")
    ap.add_argument("--sqlcmd", default="sqlcmd")
    ap.add_argument("--out", default="alig-toplama-mssql.json")
    ap.add_argument("--maskele", action="store_true", help="veritabani, dosya, giris, grup ve replika adlarini takma adla degistir")
    args = ap.parse_args(argv)
    if bool(args.kullanici) == bool(args.windows):
        raise SystemExit("--kullanici ya da --windows seceneklerinden tam olarak birini verin")
    if args.kullanici and not os.environ.get("SQLCMDPASSWORD"):
        raise SystemExit("parola SQLCMDPASSWORD ortam degiskeninde olmali")

    baglanti = ["-S", args.sunucu, "-d", "master"]
    baglanti += ["-E"] if args.windows else ["-U", args.kullanici]
    if args.sifrele:
        baglanti.append("-N")
    if args.sertifikaya_guven:
        baglanti.append("-C")

    ilk = calistir(args.sqlcmd, baglanti, "SELECT CAST(IS_SRVROLEMEMBER('sysadmin') AS int) AS yonetici")
    if ilk["durum"] != "ok" or not ilk["satirlar"]:
        raise SystemExit("baglanti kurulamadi (%s). Sunucu, giris, parola ve sifreleme seceneklerini denetleyin. SQL Server 2016 ve ustu gerekir." % ilk.get("neden"))
    yonetici = bool(ilk["satirlar"][0].get("yonetici"))
    if yonetici:
        print("UYARI: sysadmin uyesi bir girisle calisiyorsunuz. Yalnizca VIEW SERVER STATE ve VIEW ANY DEFINITION yetkili bir giris onerilir.", file=sys.stderr)

    maske = Maske() if args.maskele else None
    kontroller = {}
    for c in KATALOG["kontroller"]:
        sonuc = calistir(args.sqlcmd, baglanti, c["sql"])
        if sonuc["durum"] == "ok":
            sonuc["satirlar"] = [{k: v for k, v in s.items() if k in c["kolonlar"]} for s in sonuc["satirlar"] if isinstance(s, dict)]
            if maske:
                for satir in sonuc["satirlar"]:
                    for kolon in c["maske"]:
                        if kolon in satir:
                            satir[kolon] = maske.al(kolon, satir[kolon])
        kontroller[c["id"]] = sonuc
        print("%-26s %s" % (c["id"], sonuc["durum"] if sonuc["durum"] == "ok" else "ATLANDI (%s)" % sonuc["neden"]))

    belge = {"format": FORMAT, "motor": KATALOG["motor"], "katalog_sha256": KATALOG_OZETI,
             "olusturma_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "maskeli": bool(maske), "superuser": yonetici, "kontroller": kontroller}
    veri = json.dumps(belge, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    with open(args.out, "wb") as f:
        f.write(veri)
    print("\nYazildi: %s\nSHA-256: %s\nDosyayi acip inceleyebilirsiniz. Siteye yuklemeden once hicbir sey gonderilmedi." % (
        args.out, hashlib.sha256(veri).hexdigest()))


if __name__ == "__main__":
    main()

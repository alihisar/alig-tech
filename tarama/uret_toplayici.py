#!/usr/bin/env python3
"""Katalogdan site/assets/alig-toplayici.py ve sorgu-katalogu.txt uretir.
Kontrol: python3 tarama/uret_toplayici.py --kontrol (CI ve testler kullanir)."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tarama import katalog  # noqa: E402


def kontroller(motor="postgresql"):
    return [{k: c[k] for k in ("id", "sql", "kolonlar", "maske")} for c in katalog.MOTORLAR[motor]]


def katalog_ozeti(motor="postgresql"):
    return hashlib.sha256(json.dumps(kontroller(motor), sort_keys=True).encode()).hexdigest()


def uret_mssql():
    """On surum SQL Server toplayicisi: site/assets altina degil, tarama/onsurum altina yazilir."""
    doc = {"format": katalog.FORMAT, "motor": "mssql", "kontroller": kontroller("mssql")}
    sablon = (ROOT / "tarama" / "toplayici" / "sablon_mssql.py").read_text(encoding="utf-8")
    kod = sablon.replace("__KATALOG_JSON__", json.dumps(doc, ensure_ascii=False, sort_keys=True))
    satirlar = ["alig.tech saglik taramasi (SQL Server, on surum): calisan tum sorgular",
                "Her sorgunun sonuna FOR JSON PATH, INCLUDE_NULL_VALUES eklenir. Kilit beklemesi 2 sn, sorgu suresi 15 sn.", ""]
    for c in katalog.MSSQL:
        satirlar += ["-- " + c["id"], c["sql"], ""]
    return {"alig-toplayici-mssql.py": kod, "sorgu-katalogu-mssql.txt": "\n".join(satirlar)}


def uret():
    doc = {"format": katalog.FORMAT, "motor": katalog.MOTOR, "kontroller": kontroller()}
    sablon = (ROOT / "tarama" / "toplayici" / "sablon.py").read_text(encoding="utf-8")
    kod = sablon.replace("__KATALOG_JSON__", json.dumps(doc, ensure_ascii=False, sort_keys=True))
    satirlar = ["alig.tech saglik taramasi: calisan tum sorgular", "Her sorgu SELECT coalesce(json_agg(t),'[]') FROM (<sorgu>) t icinde,",
                "default_transaction_read_only=on, statement_timeout=15000 ile calisir.", ""]
    for c in katalog.PG:
        satirlar += ["-- " + c["id"] + (" (yetki: " + c["yetki"] + ")" if c.get("yetki") else ""), c["sql"] + ";", ""]
    return {"alig-toplayici.py": kod, "sorgu-katalogu.txt": "\n".join(satirlar)}


def main(argv):
    isler = [(ROOT / "site" / "assets", uret()), (ROOT / "tarama" / "onsurum", uret_mssql())]
    if "--kontrol" in argv:
        eski = [n for hedef, cikti in isler for n, v in cikti.items()
                if not (hedef / n).exists() or (hedef / n).read_text(encoding="utf-8") != v]
        if eski:
            print("guncel degil, calistirin: python3 tarama/uret_toplayici.py ->", ", ".join(eski))
            return 1
        return 0
    for hedef, cikti in isler:
        hedef.mkdir(exist_ok=True)
        for n, v in cikti.items():
            (hedef / n).write_text(v, encoding="utf-8")
            print("yazildi", hedef / n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

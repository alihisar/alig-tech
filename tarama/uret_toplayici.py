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


def kontroller():
    return [{k: c[k] for k in ("id", "sql", "kolonlar", "maske")} for c in katalog.PG]


def katalog_ozeti():
    return hashlib.sha256(json.dumps(kontroller(), sort_keys=True).encode()).hexdigest()


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
    cikti = uret()
    hedef = ROOT / "site" / "assets"
    if "--kontrol" in argv:
        eski = [n for n, v in cikti.items() if not (hedef / n).exists() or (hedef / n).read_text(encoding="utf-8") != v]
        if eski:
            print("guncel degil, calistirin: python3 tarama/uret_toplayici.py ->", ", ".join(eski))
            return 1
        return 0
    for n, v in cikti.items():
        (hedef / n).write_text(v, encoding="utf-8")
        print("yazildi", hedef / n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Load the demo CSVs into a SQLite DB and print the env vars that switch the packs to SQL.
Usage: python scripts/load_sqlite.py [data/demo.db]"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from caseforge.core.connectors import load_csv_into_sqlite  # noqa: E402

db = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data" / "demo.db")
db.parent.mkdir(parents=True, exist_ok=True)
P = ROOT / "caseforge" / "packs"
for table, csv_path in (("transactions", P / "bfsi/data/transactions.csv"), ("accounts", P / "bfsi/data/accounts.csv"),
                        ("sensors", P / "manufacturing/data/sensors.csv")):
    print(f"loaded {load_csv_into_sqlite(csv_path, db, table)} rows into {table}")
url = f"sqlite:///{db.resolve().as_posix()}"
print(f"\nexport CASEFORGE_BFSI_DB_URL={url}\nexport CASEFORGE_MANUFACTURING_DB_URL={url}")

"""Convert the demo CSVs to Parquet and print the env vars that switch the packs to them.
Usage: python scripts/csv_to_parquet.py [out_dir]   (default: data/parquet)"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from caseforge.core.connectors import write_parquet_from_csv  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data" / "parquet")
out.mkdir(parents=True, exist_ok=True)
P = ROOT / "caseforge" / "packs"
for pack, table, csv_path in (("BFSI", "transactions", P / "bfsi/data/transactions.csv"),
                              ("BFSI", "accounts", P / "bfsi/data/accounts.csv"),
                              ("MANUFACTURING", "sensors", P / "manufacturing/data/sensors.csv")):
    target = out / f"{table}.parquet"
    print(f"wrote {write_parquet_from_csv(csv_path, target)} rows to {target}")
    print(f"  CASEFORGE_{pack}_{table.upper()}_PARQUET={target}")

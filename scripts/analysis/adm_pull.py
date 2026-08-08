"""Throwaway: range-extract selected ADM YTD members. Read-only research helper."""
import sys, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.connectors.rma_adm import http_range_zip, ADM_CACHE_DIR

URL = "https://pubfs-rma.fpac.usda.gov/pub/References/actuarial_data_master/{y}/{y}_ADM_YTD.zip"

def rz(year=2026):
    s = requests.Session()
    s.headers["User-Agent"] = "aip-products-research/1.0"
    return http_range_zip(s, URL.format(y=year), 120)

if __name__ == "__main__":
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    z = rz(year)
    subs = sys.argv[2:]
    if not subs:
        for n, m in sorted(z.members().items()):
            print(f"{m.usize/1e6:12.2f} MB  {n}")
    else:
        ADM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for sub in subs:
            m = z.find(sub)
            dest = ADM_CACHE_DIR / (m.name if m.name.startswith(str(year)) else f"{year}_{m.name}")
            if dest.exists() and dest.stat().st_size == m.usize:
                print("cached", dest); continue
            print("pulling", m.name, f"{m.usize/1e6:.1f} MB")
            z.extract(m, dest); print("  ->", dest)

"""Regenerate data/seed/batteries.json from a transparent mass/price model.

The seed batteries are *approximate* catalogue-style packs, not specific products: pack mass
follows a specific-energy curve typical of RC LiPo / 21700 Li-ion packs. Replace or extend with
datasheet values through data/custom. Usage: python scripts/generate_seed_batteries.py
"""

import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "seed" / "batteries.json"
NOTE = "approximate generic pack; mass from specific-energy model, not a datasheet"

LIPO_CAPS = {
    3: [1300, 2200, 3000, 4000, 5000],
    4: [2200, 3000, 4000, 5000, 6000, 8000, 10000],
    6: [3000, 4000, 5000, 6000, 8000, 10000, 16000, 22000],
}
LIION_CAPS = {4: [4000, 8000, 12000], 6: [4000, 8000, 12000, 16000]}  # 21700 cells, nP packs


def lipo(cells, cap):
    wh = cells * 3.7 * cap / 1000.0
    se = 125.0 + 40.0 * (1.0 - math.exp(-cap / 5000.0))  # Wh/kg, rises with pack size
    return {
        "id": f"lipo-{cells}s-{cap}",
        "name": f"Generic LiPo {cells}S {cap} mAh",
        "chemistry": "lipo",
        "cells": cells,
        "capacity_mah": cap,
        "mass_g": round(wh / se * 1000.0 / 5.0) * 5,
        "c_rate_cont": 25 if cap <= 8000 else 20,
        "c_rate_burst": 50 if cap <= 8000 else 40,
        "price_usd": round(6.0 + 0.55 * wh),
        "verified": False,
        "notes": NOTE,
    }


def liion(cells, cap):
    parallel = cap // 4000
    cell_mass_g = 68.0
    return {
        "id": f"liion-{cells}s{parallel}p-{cap}",
        "name": f"Generic Li-ion {cells}S{parallel}P 21700 {cap} mAh",
        "chemistry": "liion",
        "cells": cells,
        "capacity_mah": cap,
        "mass_g": round(cells * parallel * cell_mass_g * 1.04 / 5.0) * 5,
        "c_rate_cont": 8,
        "c_rate_burst": 10,
        "internal_resistance_mohm": round(cells * 15.0 / parallel, 1),
        "price_usd": round(cells * parallel * 5.0 * 1.3),
        "verified": False,
        "notes": NOTE,
    }


packs = [lipo(c, cap) for c, caps in LIPO_CAPS.items() for cap in caps]
packs += [liion(c, cap) for c, caps in LIION_CAPS.items() for cap in caps]
OUT.write_text(json.dumps(packs, indent=2) + "\n", encoding="utf-8")
print(f"wrote {len(packs)} batteries to {OUT}")

"""Assegna a ogni località di dati-italia.zip la sua provincia (una tantum).

Richiede shapely e i confini provinciali ISTAT ripubblicati da openpolis/geojson-italy (CC BY 4.0):
  pip install shapely
  curl -LO https://raw.githubusercontent.com/openpolis/geojson-italy/master/geojson/limits_IT_provinces.geojson
  python3 strumenti/territorio.py limits_IT_provinces.geojson
Scrive dati/territorio.json, letto da geografia.py senza dipendenze esterne.
I confini sono quelli con 110 province: le vecchie province sarde (CI, VS, OG, OT)
sono ricondotte all'assetto a 107 province con capoluogo Carbonia per il Sud Sardegna.
"""
import json, sys
from pathlib import Path
from zipfile import ZipFile
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

# Capoluogo di ciascuna provincia, come compare nella guida (settlements.json).
CAPOLUOGO = {"AO":"Aosta","BZ":"Bolzano","BT":"Barletta","FC":"Forlì","MB":"Monza","MS":"Massa","PU":"Pesaro",
    "VB":"Verbania","RE":"Reggio Emilia","RC":"Reggio di Calabria","SU":"Carbonia"}
SARDEGNA = {"CI":"SU","VS":"SU","OG":"NU","OT":"SS"}
NOMI = {"SU":"Sud Sardegna"}

def main():
    geo = json.loads(Path(sys.argv[1]).read_text())
    root = Path(__file__).resolve().parent.parent
    with ZipFile(root/"dati-italia.zip") as z: places = json.loads(z.read("settlements.json"))
    shapes, codes, province = [], [], {}
    for f in geo["features"]:
        p = f["properties"]; code = SARDEGNA.get(p["prov_acr"], p["prov_acr"])
        shapes.append(shape(f["geometry"])); codes.append(code)
        name = NOMI.get(code, p["prov_name"] if code == p["prov_acr"] else None)
        if name: province[code] = {"nome": name.split("/")[0], "regione": p["reg_name"].split("/")[0],
            "capoluogo": CAPOLUOGO.get(code, name.split("/")[0])}
    tree = STRtree(shapes)
    out = []
    for name, lat, lon, *_ in places:
        pt = Point(lon/1e5, lat/1e5)
        hit = [i for i in tree.query(pt) if shapes[i].covers(pt)]
        if not hit: hit = [int(tree.nearest(pt))]  # località sulla costa o appena fuori dai confini semplificati
        out.append(codes[hit[0]])
    names = {p[0] for p in places}
    missing = [v["capoluogo"] for v in province.values() if v["capoluogo"] not in names]
    if missing: sys.exit("Capoluoghi assenti dalla guida: "+", ".join(missing))
    data = {"fonte": "ISTAT via openpolis/geojson-italy, CC BY 4.0", "province": dict(sorted(province.items())), "localita": out}
    (root/"dati"/"territorio.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(len(province), "province,", len(out), "località")

if __name__ == "__main__": main()

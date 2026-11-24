"""Sceglie i locali da cercare su Google Places: ristoranti senza sito né menu in OSM,
nei capoluoghi sotto obiettivo, al massimo --per-capoluogo per capoluogo (prima i più descritti).

  python3 strumenti/coda_places.py --copertura copertura.json > coda.json
  python3 strumenti/coda_places.py --province MI,RM --per-capoluogo 0 > coda.json   (tutte le città indicate, senza limite)
"""
import argparse, json, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from geografia import ROOT, Territorio, righe, chiave

def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--dataset", default=str(ROOT / "dati-italia.zip"))
    cli.add_argument("--copertura", type=Path, help="copertura.json: tiene solo i capoluoghi con mancano > 0")
    cli.add_argument("--per-capoluogo", type=int, default=60, help="0 = nessun limite")
    cli.add_argument("--province", help="sigle separate da virgola: solo questi capoluoghi, anche se già a obiettivo")
    cli.add_argument("--tipi", default="restaurant", help="tipi di locale separati da virgola (restaurant,cafe,bar,...)")
    args = cli.parse_args()
    t = Territorio(args.dataset); province = t.province
    sotto = set(province)
    if args.copertura:
        sotto = {r["provincia"] for r in json.loads(args.copertura.read_text())["capoluoghi"] if r["mancano"] > 0}
    if args.province: sotto = set(args.province.upper().split(","))
    tipi = set(args.tipi.split(","))
    per = defaultdict(list)
    for r in righe(args.dataset):
        if r[4] not in tipi or r[9] or r[12] or not r[3].strip(): continue
        localita, sigla, _ = t.luogo(r)
        if sigla in sotto and chiave(localita) == chiave(province[sigla]["capoluogo"]): per[sigla].append(r)
    coda = []
    for sigla, rs in sorted(per.items()):
        rs.sort(key=lambda r: (-sum(bool(r[i]) for i in (5, 7, 8, 10)), r[0]))
        coda += [{"osm_id": "osm-" + r[0], "nome": r[3], "lat": int(r[1]) / 1e5, "lon": int(r[2]) / 1e5, "provincia": sigla}
                 for r in (rs[:args.per_capoluogo] if args.per_capoluogo else rs)]
    json.dump(coda, sys.stdout, ensure_ascii=False)
    print(f"{len(coda)} locali in {len(per)} capoluoghi", file=sys.stderr)

if __name__ == "__main__": main()

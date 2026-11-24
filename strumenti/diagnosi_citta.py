"""Perché i locali di una città non hanno ancora un menu verificato: esiti della raccolta,
motivi di scarto della verifica e piattaforme dei siti senza menu.

  python3 strumenti/diagnosi_citta.py raccolta/esiti.ndjson verifica --province MI,RM
"""
import argparse, json, random, sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from geografia import ROOT, Territorio, righe, chiave

PIATTAFORME = ("facebook", "instagram", "wix", "squarespace", "jimdo", "business.site", "thefork", "tripadvisor",
               "linktr", "deliveroo", "justeat", "glovo", "ubereats", "google", "wordpress", "shopify", "webflow")

def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("esiti", type=Path); cli.add_argument("verifica", type=Path)
    cli.add_argument("--province", default="MI,RM"); cli.add_argument("--dataset", default=str(ROOT / "dati-italia.zip"))
    args = cli.parse_args()
    sigle = set(args.province.split(","))
    t = Territorio(args.dataset); pv = t.province
    citta = {}
    for r in righe(args.dataset):
        loc, sig, _ = t.luogo(r)
        if sig in sigle and chiave(loc) == chiave(pv[sig]["capoluogo"]): citta[r[0]] = (sig, r)
    esiti = {}
    for l in args.esiti.read_text().splitlines():
        if l.strip():
            e = json.loads(l)
            if e["id"] in citta: esiti[e["id"]] = e
    verificati = {v["id"][4:] for v in json.loads((args.verifica / "prezzi-verificati.json").read_text())["venues"]}
    scarti = {s["id"]: s["motivo"] for s in json.loads((args.verifica / "scarti.json").read_text())}
    random.seed(3)
    for sig in sorted(sigle):
        ids = [i for i, (s, _) in citta.items() if s == sig]
        print(f"\n## {pv[sig]['capoluogo']} ({sig}): {len(ids)} locali in mappa")
        tipi = Counter(citta[i][1][4] for i in ids)
        print("Tipi:", dict(tipi.most_common()))
        con_sito = [i for i in ids if citta[i][1][9] or citta[i][1][12]]
        print(f"Con sito o menu in mappa: {len(con_sito)}; controllati dalla raccolta: {sum(i in esiti for i in ids)}; verificati: {sum(i in verificati for i in ids)}")
        stati = Counter(esiti[i].get("status") for i in ids if i in esiti)
        print("Esiti raccolta:", dict(stati.most_common()))
        motivi = Counter(scarti[i].split(" ")[0] + " " + " ".join(scarti[i].split(" ")[2:]) if scarti[i].startswith("solo") else scarti[i] for i in ids if i in scarti)
        print("Scarti della verifica:", dict(motivi.most_common(8)))
        senza = [i for i in ids if i in esiti and esiti[i].get("status") in ("nessun_menu", "non_accessibile") or (i in esiti and esiti[i].get("status", "").startswith("http_"))]
        dom = Counter()
        for i in senza:
            host = urlsplit(citta[i][1][9] or citta[i][1][12]).netloc.lower()
            dom[next((p for p in PIATTAFORME if p in host), "sito proprio")] += 1
        print("Siti senza menu letto, per piattaforma:", dict(dom.most_common()))
        nessuno = [i for i in senza if esiti[i].get("status") == "nessun_menu"]
        for i in random.sample(nessuno, min(15, len(nessuno))): print("   nessun menu:", citta[i][1][3], "·", citta[i][1][9])
        pochi = [i for i in ids if scarti.get(i, "").startswith("solo") and "piatti" in scarti[i]]
        for i in random.sample(pochi, min(8, len(pochi))):
            pag = max(esiti[i].get("pages", []), key=lambda p: len(p.get("candidates", [])), default={})
            print("   pochi piatti:", citta[i][1][3], "·", scarti[i], "·", pag.get("url"), [c.get("name") for c in pag.get("candidates", [])][:5])

if __name__ == "__main__": main()

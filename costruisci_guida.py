"""Divide la guida nazionale in file piccoli per la pagina del voto.

  python3 costruisci_guida.py
Scrive guida/localita.json (località con almeno un locale) e guida/z/NN.json
(i locali di un gruppo di località: id, nome, tipo, indirizzo, "lat,lon" e 1 se il menu è verificato). La pagina scarica solo il file della località scelta.
"""
import hashlib, json, shutil
from collections import defaultdict
from geografia import ROOT, Territorio, righe, chiave

FILE = 256
TIPI = {"restaurant": "Ristorante", "cafe": "Caffè", "bar": "Bar", "fast_food": "Fast food", "ice_cream": "Gelateria",
        "pub": "Pub", "biergarten": "Birreria", "food_court": "Food court"}

def gruppo(nome, sigla):
    return int(hashlib.sha256(f"{nome}|{sigla}".encode()).hexdigest(), 16) % FILE

def verificati():
    """Nomi e città dei locali con menu verificato in menus.json."""
    venues = json.loads((ROOT / "menus.json").read_text())["venues"]
    return {(chiave(v["name"]), chiave(v.get("city"))) for v in venues if v.get("dishes")}

def main():
    territorio, menu = Territorio(), verificati()
    per_luogo = defaultdict(list)
    for r in righe(ROOT / "dati-italia.zip"):
        if not r[3].strip(): continue
        nome, sigla, _ = territorio.luogo(r)
        via = r[7] if not r[6] or chiave(r[6]) == chiave(nome) else ", ".join(filter(None, (r[7], r[6])))
        voce = ["osm-" + r[0], r[3].strip(), TIPI.get(r[4], ""), via.strip(), f"{int(r[1]) / 1e5:.5f},{int(r[2]) / 1e5:.5f}"]
        if (chiave(r[3]), chiave(r[6] or nome)) in menu: voce.append(1)
        per_luogo[(nome, sigla)].append(voce)
    out = ROOT / "guida"
    shutil.rmtree(out, ignore_errors=True); (out / "z").mkdir(parents=True)
    file, elenco = defaultdict(dict), []
    for (nome, sigla), locali in per_luogo.items():
        locali.sort(key=lambda v: (-len(v), v[2] != "Ristorante", chiave(v[1])))
        n = gruppo(nome, sigla)
        file[n][f"{nome}|{sigla}"] = locali
        elenco.append([nome, sigla, len(locali), n])
    for n, data in file.items():
        (out / "z" / f"{n:02x}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    elenco.sort(key=lambda x: -x[2])
    (out / "localita.json").write_text(json.dumps({"province": {k: v["nome"] for k, v in territorio.province.items()},
        "localita": elenco}, ensure_ascii=False, separators=(",", ":")))
    print(len(elenco), "località,", sum(x[2] for x in elenco), "locali,", len(file), "file")

if __name__ == "__main__": main()

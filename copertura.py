"""Misura l'obiettivo: almeno 10 locali con menu verificato in ognuno dei capoluoghi di provincia.

  python3 copertura.py [esiti.ndjson ...] --output copertura
Conta i locali di menus.json (verificati) e, se passati, gli esiti della raccolta con prezzi
trovati ma non ancora verificati. Scrive copertura.json e copertura.md.
"""
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path
from geografia import ROOT, chiave

OBIETTIVO = 10
MIN_PREZZI = 5  # sotto questa soglia una pagina con prezzi non basta per dire "menu trovato"

def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("esiti", nargs="*", type=Path)
    cli.add_argument("--output", type=Path, default=Path("copertura"))
    cli.add_argument("--verificati", type=Path, help="prezzi-verificati.json di verifica_prezzi.py: contano come verificati")
    args = cli.parse_args()
    province = json.loads((ROOT / "dati" / "territorio.json").read_text())["province"]
    capoluogo = {chiave(p["capoluogo"]): sigla for sigla, p in province.items()}
    verificati, candidati = defaultdict(set), defaultdict(set)
    regioni_verificati, regioni_candidati = Counter(), Counter()
    for v in json.loads((ROOT / "menus.json").read_text())["venues"]:
        if not v.get("dishes"): continue
        sigla = capoluogo.get(chiave(v.get("city")))
        if sigla: verificati[sigla].add(chiave(v["name"]))
    if args.verificati and args.verificati.exists():
        for v in json.loads(args.verificati.read_text())["venues"]:
            sigla = v.get("provincia")
            if sigla in province and chiave(v.get("city")) == chiave(province[sigla]["capoluogo"]):
                verificati[sigla].add(chiave(v["name"]))
    righe = 0
    for path in args.esiti:
        for line in path.read_text().splitlines():
            if not line.strip(): continue
            row = json.loads(line); righe += 1
            prezzi = sum(len(p.get("candidates", [])) for p in row.get("pages", []))
            if prezzi < MIN_PREZZI: continue
            sedi = [row, *row.get("altre_sedi", [])]
            for sede in sedi:
                if sede.get("regione") or row.get("regione"): regioni_candidati[sede.get("regione") or row.get("regione")] += 1
                sigla = sede.get("provincia") or row.get("provincia")
                if sigla and chiave(sede.get("localita")) == chiave(province.get(sigla, {}).get("capoluogo")):
                    candidati[sigla].add(chiave(sede["name"]))
    righe_out, per_regione = [], defaultdict(lambda: {"capoluoghi": 0, "a_obiettivo": 0, "verificati": 0, "candidati": 0})
    for sigla, p in sorted(province.items(), key=lambda kv: (kv[1]["regione"], kv[1]["capoluogo"])):
        v = len(verificati[sigla]); c = len(candidati[sigla] - verificati[sigla])
        righe_out.append({"provincia": sigla, "capoluogo": p["capoluogo"], "regione": p["regione"], "verificati": v,
                          "da_verificare": c, "mancano": max(0, OBIETTIVO - v)})
        r = per_regione[p["regione"]]; r["capoluoghi"] += 1; r["a_obiettivo"] += v >= OBIETTIVO
        r["verificati"] += v; r["candidati"] += c
    for nome, r in per_regione.items(): r["locali_con_prezzi_in_regione"] = regioni_candidati[nome]
    totale = {"capoluoghi": len(righe_out), "a_obiettivo": sum(r["verificati"] >= OBIETTIVO for r in righe_out),
              "con_almeno_un_menu": sum(r["verificati"] > 0 for r in righe_out),
              "raggiungibili_con_i_candidati": sum(r["verificati"] + r["da_verificare"] >= OBIETTIVO for r in righe_out),
              "esiti_letti": righe}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "copertura.json").write_text(json.dumps({"obiettivo": OBIETTIVO, "totale": totale,
        "regioni": dict(sorted(per_regione.items())), "capoluoghi": righe_out}, ensure_ascii=False, indent=1))
    md = [f"### Copertura menu: {totale['a_obiettivo']} capoluoghi su {totale['capoluoghi']} hanno almeno {OBIETTIVO} locali verificati", "",
          f"Con almeno un menu verificato: {totale['con_almeno_un_menu']}. Arriverebbero a {OBIETTIVO} verificando i prezzi trovati: {totale['raggiungibili_con_i_candidati']}.", "",
          "|Regione|Capoluoghi a obiettivo|Locali verificati nei capoluoghi|Da verificare nei capoluoghi|Locali con prezzi trovati in regione|", "|---|---:|---:|---:|---:|"]
    md += [f"|{n}|{r['a_obiettivo']} di {r['capoluoghi']}|{r['verificati']}|{r['candidati']}|{r['locali_con_prezzi_in_regione']}|" for n, r in sorted(per_regione.items())]
    md += ["", "|Capoluogo|Verificati|Da verificare|Mancano|", "|---|---:|---:|---:|"]
    md += [f"|{r['capoluogo']} ({r['provincia']})|{r['verificati']}|{r['da_verificare']}|{r['mancano']}|" for r in righe_out]
    (args.output / "copertura.md").write_text("\n".join(md) + "\n")
    print(md[0]); print(md[2])

if __name__ == "__main__": main()

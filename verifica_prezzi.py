"""Verifica automatica dei prezzi trovati dalla raccolta.

  python3 verifica_prezzi.py esiti.ndjson --output verifica
Promuove un locale solo se una sua pagina ha un menu credibile:
- almeno MIN_PIATTI piatti con nome e prezzo, con almeno 4 prezzi diversi;
- prezzi plausibili per il tipo di locale e mediana in una fascia sensata;
- la maggior parte dei nomi sembra un piatto o una bevanda (vocabolario di cucina);
- pochi nomi ripetuti o troppo lunghi (righe di testo e non piatti).
Scrive prezzi-verificati.json (stesse chiavi di menus.json, più "verifica" e "punteggio")
e scarti.json con il motivo di ogni locale escluso.
"""
import argparse, json, random, re, statistics
from collections import Counter
from pathlib import Path

MIN_PIATTI = 8
MAX_PIATTI = 80
FASCE = {  # centesimi: prezzo minimo, massimo e mediana ammessa per tipo di locale
    "restaurant": (100, 15000, (400, 4500)),
    "fast_food": (50, 6000, (250, 2500)),
    "cafe": (50, 5000, (100, 1500)),
    "bar": (50, 5000, (100, 1800)),
    "pub": (100, 6000, (300, 2500)),
    "ice_cream": (50, 4000, (150, 1200)),
    "biergarten": (100, 6000, (300, 2500)),
}
PAROLE = """
pizz\\w* margherita marinara diavola capricciosa calzon\\w* focacc\\w* pinsa piadin\\w* panin\\w* toast tramezzin\\w* bruschett\\w* crostin\\w*
pasta spaghett\\w* linguin\\w* tagliatell\\w* tagliolin\\w* pappardell\\w* fettuccin\\w* tortell\\w* tortellin\\w* cappellett\\w* ravioli\\w* agnolott\\w* lasagn\\w* gnocch\\w*
penne rigatoni paccheri orecchiette trofie bigoli pici tonnarelli bucatini maccheron\\w* fusilli mezze strozzapreti passatelli
carbonara amatriciana gricia cacio pepe ragu ragù bolognese pesto pomodor\\w* sugo
risott\\w* riso zupp\\w* minestr\\w* vellutat\\w* brodo ribollita polenta
antipast\\w* primi secondi contorn\\w* dolc\\w* dessert frutta
carne manzo vitell\\w* maial\\w* pollo tacchino agnello coniglio anatra cinghiale salsicc\\w* bistecc\\w* tagliata filetto costat\\w* fiorentina hamburger burger cotolett\\w* arrost\\w* brasat\\w* spezzatino ossobuco porchetta polpett\\w* grigliat\\w* fritt\\w* frittura
pesce tonno salmone baccal\\w* merluzzo orata branzino spigola pesce\\w* gamber\\w* scamp\\w* calamar\\w* polpo seppi\\w* cozze vongole frutti mare acciughe alici sarde crudo tartare carpaccio sushi sashimi uramaki nigiri
prosciutto salame mortadella speck bresaola salumi coppa lardo guanciale pancetta
formagg\\w* mozzarell\\w* burrata bufala parmigiano grana pecorino gorgonzola ricotta stracciatella scamorza
insalat\\w* verdur\\w* patat\\w* melanzan\\w* zucchin\\w* funghi porcini carciof\\w* spinaci rucola radicchio cipoll\\w* olive legumi ceci fagioli lenticchie tartufo
tiramis\\w* panna cotta cannol\\w* sfogliatell\\w* babà baba torta crostata cheesecake gelat\\w* sorbetto semifreddo biscott\\w* cornett\\w* brioche croissant
caffè caffe espresso cappuccin\\w* macchiat\\w* ginseng latte tè the tisana cioccolat\\w* spremut\\w* succo succhi
acqua birr\\w* vino vini rosso bianco bollicine prosecco spritz negroni cocktail amaro grappa limoncello liquor\\w* calice bottiglia
uovo uova frittata kebab piadina arrosticin\\w* olive ascolane supplì suppli arancin\\w* crocchett\\w* nachos chips wurstel
tagliere taglier\\w* caprese parmigiana tonnato bollit\\w* trippa lampredotto cacciucco canederl\\w* spatzle spätzle pizzoccher\\w* casoncell\\w* cassoeula saor cicchett\\w* scaloppin\\w* saltimbocca involtin\\w* polent\\w* tigell\\w* gnocco crescentin\\w* erbazzone cappellacc\\w* culurgion\\w* malloreddus fregola seadas porcedd\\w* caponata panell\\w* sfincion\\w* cassata granit\\w* friarielli scarola pastiera zeppol\\w* mozzarelline fiori zucca zucch\\w* asparag\\w* piselli bisi broccol\\w* cavol\\w* peperon\\w* noci nocciol\\w* pistacchi\\w* mandorl\\w* miele marmellat\\w* nutella crema creme mascarpone fragol\\w* lampon\\w* limone arancia mela pera ananas frutti bosco
ramen udon soba gyoza gyoza dim sum bao noodle\\w* dumpling\\w* tempura edamame maki uramaki temaki hosomaki futomaki chirashi onigiri poke pokè teriyaki katsu miso wakame wok cantonese involtino primavera curry tikka masala tandoori naan biryani samosa pakora dal paneer korma vindaloo pad thai satay falafel hummus couscous tajine kebap shawarma paella tapas tacos taco burrito quesadilla fajitas guacamole hot dog
chicken beef pork lamb duck fish salmon tuna shrimp shrimps prawn\\w* octopus squid salad soup cheese cake pie bread rice egg eggs fries steak burger\\w* sandwich\\w* wrap\\w* bowl veggie vegan tofu mushroom\\w* tomato\\w* potato\\w* beer wine coffee tea juice water ice cream
gin rum vodka whisky whiskey tequila mojito americano martini daiquiri margarita moscow mule tonic bibit\\w* coca cola aranciata chinotto analcolic\\w* lambrusco chianti barolo brunello montepulciano primitivo vermentino falanghina franciacorta champagne sangria sidro
"""
CIBO = re.compile(r"\b(" + "|".join(PAROLE.split()) + r")\b", re.I)
# Vocabolario della prima versione: serve solo a mostrare nel log i locali accettati grazie alle parole nuove.
CIBO_BASE = re.compile(r"\b(" + "|".join(PAROLE[:PAROLE.index("tagliere")].split()) + r")\b", re.I)

# Righe con prezzo che non sono un piatto: formati, supplementi, menu fissi generici, quantità.
NON_PIATTO = re.compile(r"^(?:\(?\d+\s*(?:pz|pezzi|cl|ml|l|lt|gr?)\b|al\s+(?:pz|pezzo|kg|etto|hg)|bottiglia|calice|caraffa|menù\s+(?:da|base|completo|intermedio|degustazione)?\s*$|menu\s+da\b|\d+\s+portate|senza glutine|impasto|aggiunta|supplemento|extra\b|doppi[ao]\b|maxi\b|baby\b|piccol[ao]\b|medi[ao]\b|grande\b|intera\b|mezza\b|½|1/2)", re.I)
DESCRIZIONE = re.compile(r"^(?:con|servit[oaie]|accompagnat[oaie]|leggermente|su letto|al profumo|e\s)\b")

def pulisci(nome):
    """None se la riga non è un piatto pubblicabile."""
    if NON_PIATTO.search(nome) or len(nome) < 3: return None
    if nome[:1].islower() and (DESCRIZIONE.search(nome) or "," in nome): return None  # solo ingredienti, il nome del piatto è altrove
    return nome

def punteggio(pagina, tipo, soglia_cibo=0.45):
    piatti, visti = [], set()
    for c in pagina.get("candidates", []):
        nome, cents = " ".join(str(c.get("name", "")).split()), c.get("cents")
        chiave = (nome.casefold(), cents)
        if not nome or not isinstance(cents, int) or chiave in visti or not pulisci(nome): continue
        visti.add(chiave); piatti.append({"name": nome, "cents": cents})
    if len(piatti) < MIN_PIATTI: return None, f"solo {len(piatti)} piatti"
    lo, hi, (mlo, mhi) = FASCE.get(tipo, FASCE["restaurant"])
    fuori = [p for p in piatti if not lo <= p["cents"] <= hi]
    if len(fuori) > len(piatti) * 0.1: return None, f"{len(fuori)} prezzi fuori fascia"
    piatti = [p for p in piatti if lo <= p["cents"] <= hi]
    prezzi = [p["cents"] for p in piatti]
    if len(set(prezzi)) < 4: return None, "meno di 4 prezzi diversi"
    mediana = statistics.median(prezzi)
    if not mlo <= mediana <= mhi: return None, f"mediana {mediana / 100:.2f} € fuori fascia"
    cibo = sum(bool(CIBO.search(p["name"])) for p in piatti) / len(piatti)
    if cibo < soglia_cibo: return None, f"solo {cibo:.0%} dei nomi sembra un piatto"
    lunghi = sum(len(p["name"]) > 70 or len(p["name"].split()) > 12 for p in piatti) / len(piatti)
    if lunghi > 0.25: return None, "troppe righe lunghe"
    nomi = Counter(p["name"].casefold() for p in piatti)
    if nomi.most_common(1)[0][1] > max(3, len(piatti) * 0.2): return None, "nomi ripetuti"
    score = round(min(1, len(piatti) / 30) * 0.4 + cibo * 0.5 + (1 - lunghi) * 0.1, 3)
    base = sum(bool(CIBO_BASE.search(p["name"])) for p in piatti) / len(piatti)
    return {"piatti": piatti[:MAX_PIATTI], "score": score, "cibo": round(cibo, 2), "parole_nuove": base < 0.45, "metodi": Counter(c.get("method") for c in pagina["candidates"])}, ""

def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("esiti", type=Path)
    cli.add_argument("--documenti", type=Path, nargs="*", default=[], help="documenti.ndjson di leggi_menu_documenti.py (PDF e foto letti con OCR)")
    cli.add_argument("--output", type=Path, default=Path("verifica"))
    cli.add_argument("--campione", type=int, default=25, help="locali da stampare per il controllo a occhio")
    args = cli.parse_args()
    venues, scarti, motivi, fonti, unioni, parole_nuove = [], [], Counter(), set(), set(), set()
    righe = [json.loads(l) for l in args.esiti.read_text().splitlines() if l.strip()]
    per_id = {r["id"]: r for r in righe}
    for path in args.documenti:
        # Ogni PDF o foto letto diventa una pagina in più del locale che lo pubblica.
        for line in path.read_text().splitlines():
            if not line.strip(): continue
            doc = json.loads(line)
            candidati = [c for p in doc.get("pages", []) for c in p.get("candidates", [])]
            row = next((per_id[v["id"]] for v in doc.get("venues", []) if v.get("id") in per_id), None)
            if not candidati or row is None: continue
            row.setdefault("pages", []).append({"url": doc["url"], "type": "pdf", "candidates": candidati})
            row["status"] = "prezzi_candidati"
    for row in righe:
        best, motivo = None, "nessuna pagina con prezzi"
        pagine = [p for p in row.get("pages", []) if p.get("candidates")]
        for pagina in pagine:
            esito, perche = punteggio(pagina, row.get("kind"))
            if esito and (not best or esito["score"] > best[0]["score"]): best = (esito, pagina["url"])
            if esito and esito["parole_nuove"]: parole_nuove.add(row["id"])
            elif not esito: motivo = perche
        if not best and len(pagine) > 1:
            # Menu diviso su più pagine o file (antipasti, primi, vini...): si valuta l'insieme, con gli stessi controlli.
            esito, perche = punteggio({"candidates": [c for p in pagine for c in p["candidates"]]}, row.get("kind"), soglia_cibo=0.6)
            if esito: best = (esito, max(pagine, key=lambda p: len(p["candidates"]))["url"]); unioni.add(row["id"])
        if row.get("status") != "prezzi_candidati": continue
        if not best:
            motivi[re.sub(r"\d+(?:[.,]\d+)?", "N", motivo)] += 1
            scarti.append({"id": row["id"], "name": row.get("name"), "motivo": motivo}); continue
        esito, url = best
        # Una sola scheda per fonte: le catene con lo stesso menu su più sedi restano alla prima.
        if url in fonti: continue
        fonti.add(url)
        venues.append({"id": "osm-" + row["id"], "name": row.get("name"),
            "city": row.get("localita") or row.get("city"), "provincia": row.get("provincia"),
            "regione": row.get("regione"), "source": url, "checkedOn": row.get("checkedOn"),
            "verifica": "automatica", "punteggio": esito["score"], "dishes": esito["piatti"]})
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "prezzi-verificati.json").write_text(json.dumps({"schema": 1, "venues": venues}, ensure_ascii=False, indent=1))
    (args.output / "scarti.json").write_text(json.dumps(scarti, ensure_ascii=False, indent=1))
    print(f"Verificati automaticamente: {len(venues)} locali ({sum(len(v['dishes']) for v in venues)} piatti). Scartati: {len(scarti)}.")
    uniti = [v for v in venues if v["id"][4:] in unioni]
    print(f"  di cui verificati unendo più pagine dello stesso locale: {len(uniti)}")
    nuove = [v for v in venues if v["id"][4:] in parole_nuove]
    print(f"  di cui verificati grazie al vocabolario esteso: {len(nuove)}")
    for m, n in motivi.most_common(): print(f"  scarto: {m}: {n}")
    random.seed(7)
    for v in random.sample(venues, min(args.campione, len(venues))):
        print(f"\n[OK {v['punteggio']}] {v['name']} · {v['city']} ({v['provincia']}) · {v['source']}")
        for d in v["dishes"][:8]: print(f"    {d['name']} — {d['cents'] / 100:.2f} €")
    for v in random.sample(uniti, min(8, len(uniti))):
        print(f"\n[OK unione {v['punteggio']}] {v['name']} · {v['city']} ({v['provincia']}) · {v['source']}")
        for d in v["dishes"][:8]: print(f"    {d['name']} — {d['cents'] / 100:.2f} €")
    for v in random.sample(nuove, min(8, len(nuove))):
        print(f"\n[OK parole nuove {v['punteggio']}] {v['name']} · {v['city']} ({v['provincia']}) · {v['source']}")
        for d in v["dishes"][:8]: print(f"    {d['name']} — {d['cents'] / 100:.2f} €")
    ko = [s for s in scarti if not s["motivo"].startswith("solo") or "piatto" in s["motivo"]]
    for s in random.sample(ko, min(10, len(ko))): print(f"[NO] {s['name']}: {s['motivo']}")

if __name__ == "__main__": main()

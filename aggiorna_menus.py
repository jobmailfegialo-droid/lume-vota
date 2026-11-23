"""Aggiorna menus.json con i risultati della raccolta settimanale e scrive il riassunto per la PR.

Regole (prudenti per scelta):
- i locali già pubblicati si aggiornano solo dalla loro fonte (source o menuPage);
- un prezzo cambia solo se il piatto ha un solo prezzo nella fonte e la variazione è plausibile,
  altrimenti finisce tra le anomalie e resta il prezzo vecchio;
- i locali nuovi entrano solo con abbastanza piatti, prezzi sensati e fonte https,
  con un tetto settimanale che dà la precedenza alle città con meno locali (copertura in tutta Italia);
- nessun locale o piatto viene mai cancellato in automatico;
- il file finale deve passare gli stessi controlli che fa l'app (validFeed), altrimenti lo script si ferma.
"""
import argparse
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import statistics
import sys
import unicodedata
from urllib.parse import urlsplit
from zipfile import ZipFile

# Revisione minima nota del bundle dell'app (build 2026112316 da lume-app): il feed viene ignorato se non è più alta.
# Lo script legge comunque quella vera dal bundle caricato da app.html e usa la più alta.
BUNDLE_REVISION = 2026112316
TRUSTED = {"schema_menuitem", "stessa_riga", "pdf_testo_allineato"}
WEAK = {"riga_precedente", "ocr_riga"}
MIN_CENTS, MAX_CENTS = 100, 15000
MAX_RATIO = 1.6  # oltre +60% o sotto -37,5% il cambio è un'anomalia
MASSIVE_SHARE = 0.30  # se cambia più del 30% dei prezzi confrontati, non si applica nulla
NEW_MIN_DISHES, NEW_MAX_DISHES = 8, 150
NEW_PER_CITY = 5


def norm_name(text):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def norm_url(url):
    try:
        p = urlsplit(url or "")
    except ValueError:
        return ""
    host = (p.hostname or "").lower().removeprefix("www.")
    return host + (p.path.rstrip("/") or "") + ("?" + p.query if p.query else "") if host else ""


def https(url):
    return isinstance(url, str) and re.match(r"^https://[^\s/]+(?:/|$)", url) is not None


def read_ndjson(root, name):
    for file in sorted(Path(root).rglob(name)):
        with file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue


def load_sources(results):
    """url normalizzato -> {url, venues:[{id,name,city}], items:[{name,cents,method}], shared}"""
    sources = {}

    def add(url, venues, items, shared=False):
        key = norm_url(url)
        if not key:
            return
        src = sources.setdefault(key, {"url": url, "venues": [], "items": [], "shared": False})
        seen = {v["id"] for v in src["venues"]}
        src["venues"] += [v for v in venues if v.get("id") and v["id"] not in seen]
        src["items"] += [i for i in items if isinstance(i, dict) and i.get("name") and isinstance(i.get("cents"), int)]
        src["shared"] |= shared or len(src["venues"]) > 1

    for row in read_ndjson(results, "esiti.ndjson"):
        venues = [{"id": row.get("id"), "name": row.get("name"), "city": row.get("city")}] + row.get("altre_sedi", [])
        for page in row.get("pages", []):
            add(page.get("url"), venues, page.get("candidates", []), bool(row.get("fonte_condivisa")))
    for doc in read_ndjson(results, "documenti.ndjson"):
        items = [i for p in doc.get("pages", []) for i in p.get("candidates", [])]
        add(doc.get("url"), doc.get("venues", []), items)
    return sources


def price_index(items, methods):
    """nome normalizzato -> insieme di prezzi trovati (solo metodi ammessi)"""
    idx = defaultdict(set)
    for i in items:
        if i.get("method") in methods and MIN_CENTS <= i["cents"] <= MAX_CENTS:
            idx[norm_name(i["name"])].add(i["cents"])
    return idx


def euro(cents):
    return f"{cents / 100:.2f}".replace(".", ",") + " €"


def update_existing(venues, sources, today):
    changes, anomalies, confirmed, missing = [], [], 0, []
    plan, total_found = [], 0
    for v in venues:
        keys = {norm_url(v.get("source")), norm_url(v.get("menuPage"))} - {""}
        items = [i for k in keys if k in sources for i in sources[k]["items"]]
        if not items:
            continue
        strong, all_methods = price_index(items, TRUSTED), price_index(items, TRUSTED | WEAK)
        found = 0
        for d in v["dishes"]:
            names = {norm_name(d["name"]), norm_name(d.get("anchor"))} - {""}
            seen_any = set().union(*(all_methods.get(n, set()) for n in names))
            seen_strong = set().union(*(strong.get(n, set()) for n in names))
            if not seen_any:
                continue
            found += 1
            total_found += 1
            old = d.get("cents")
            if old in seen_any:
                continue  # prezzo confermato, anche da OCR
            if len(seen_strong) != 1:
                if seen_strong or seen_any:
                    anomalies.append((v, d, old, sorted(seen_any), "più prezzi o lettura incerta (OCR)"))
                continue
            new = next(iter(seen_strong))
            ratio = new / old if old else math.inf
            if not (1 / MAX_RATIO <= ratio <= MAX_RATIO):
                anomalies.append((v, d, old, [new], f"variazione {ratio - 1:+.0%}"))
                continue
            plan.append((v, d, old, new))
        if found and found >= max(1, len(v["dishes"]) // 2):
            confirmed += 1
            v["_checked"] = True
        elif v["dishes"]:
            missing.append((v, found))
    blocked = len(plan) >= 10 and len(plan) > MASSIVE_SHARE * total_found
    if blocked:
        anomalies += [(v, d, old, [new], "bloccato: troppi cambi nella stessa settimana") for v, d, old, new in plan]
        plan = []
    for v, d, old, new in plan:
        d["cents"] = new
        changes.append((v, d, old, new))
    for v in venues:
        if v.pop("_checked", False):
            v["checkedOn"] = today
    return changes, anomalies, confirmed, missing, blocked


def dataset_lookup(archive):
    rows, places = {}, []
    with ZipFile(archive) as z:
        for block in json.loads(z.read("cells.json")).values():
            for line in block.splitlines():
                r = (line.split("\t") + [""] * 13)[:13]
                if r[0]:
                    rows[r[0]] = r
        places = [(p[0], p[1], p[2]) for p in json.loads(z.read("settlements.json"))]
    return rows, places


def nearest_place(places, lat, lon):
    best = min(places, key=lambda p: (p[1] - lat) ** 2 + ((p[2] - lon) * 0.75) ** 2)
    return best[0]


def new_venues(sources, existing, rows, places, today, limit):
    taken_urls = {norm_url(v.get(k)) for v in existing for k in ("source", "menuPage")} - {""}
    taken_ids = {v["id"] for v in existing}
    per_city = Counter(v["city"] for v in existing)
    proposals, skipped = [], Counter()
    for key, src in sources.items():
        if key in taken_urls or not src["venues"]:
            continue
        if src["shared"]:
            skipped["fonte condivisa da più sedi (catena)"] += 1
            continue
        if not https(src["url"]):
            skipped["fonte non https"] += 1
            continue
        venue = src["venues"][0]
        if venue["id"] in taken_ids:
            continue
        by_name = defaultdict(set)
        label = {}
        for i in src["items"]:
            if i.get("method") in TRUSTED and MIN_CENTS <= i["cents"] <= MAX_CENTS:
                n = norm_name(i["name"])
                if len(n) >= 3:
                    by_name[n].add(i["cents"])
                    label.setdefault(n, i["name"].strip())
        dishes = [{"name": label[n], "cents": next(iter(p))} for n, p in by_name.items() if len(p) == 1]
        if len(dishes) < NEW_MIN_DISHES:
            skipped["meno di %d piatti sicuri" % NEW_MIN_DISHES] += 1
            continue
        prices = [d["cents"] for d in dishes]
        median = statistics.median(prices)
        if not 300 <= median <= 6000:
            skipped["prezzo mediano fuori scala"] += 1
            continue
        if len(set(prices)) < 3:
            skipped["prezzi tutti uguali (probabile errore di lettura)"] += 1
            continue
        r = rows.get(venue["id"])
        city = (venue.get("city") or (r[6] if r else "")).strip()
        if not city and r and r[1].lstrip("-").isdigit() and r[2].lstrip("-").isdigit():
            city = nearest_place(places, int(r[1]), int(r[2]))
        if not city:
            skipped["città sconosciuta"] += 1
            continue
        record = {"id": venue["id"], "name": (venue.get("name") or (r[3] if r else "")).strip(), "city": city}
        if not record["name"]:
            skipped["nome mancante"] += 1
            continue
        if venue["id"] in {c["id"] for c in proposals}:
            continue
        if r and r[7]:
            record["street"] = r[7]
        if r and r[8]:
            record["phone"] = r[8]
        record.update({"source": src["url"], "checkedOn": today, "origin": "raccolta-automatica",
                       "dishes": sorted(dishes, key=lambda d: norm_name(d["name"]))[:NEW_MAX_DISHES]})
        proposals.append(record)
    # Precedenza alle città con meno locali e tetto per città, così la copertura cresce in tutta Italia.
    proposals.sort(key=lambda v: (per_city[v["city"]], -len(v["dishes"]), v["id"]))
    chosen, added_in_city = [], Counter()
    for v in proposals:
        if len(chosen) >= limit:
            skipped["oltre il tetto settimanale"] += 1
            continue
        if added_in_city[v["city"]] >= NEW_PER_CITY:
            skipped["già %d nuovi nella stessa città questa settimana" % NEW_PER_CITY] += 1
            continue
        added_in_city[v["city"]] += 1
        taken_ids.add(v["id"])
        chosen.append(v)
    return chosen, skipped


def bundle_revision(app_html):
    """Legge la revisione incorporata nel bundle che app.html carica (se presente)."""
    try:
        html = Path(app_html).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    found = 0
    for src in re.findall(r'src="([^"]+\.js)"', html):
        path = Path(app_html).parent / src.split("?")[0].lstrip("/")
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"(\d{10})\s*,\s*[\w$]+\s*=\s*['\"]https://[^'\"]*/menus\.json['\"]", text):
                found = max(found, int(m.group(1)))
    return found


def valid_feed(feed, min_revision):
    """Copia dei controlli di validFeed nell'app: se uno fallisce, l'app scarta l'intero file."""
    errors = []
    if feed.get("schema") != 1:
        errors.append("schema diverso da 1")
    rev = feed.get("revision")
    if not isinstance(rev, int) or rev <= min_revision:
        errors.append(f"revision {rev} non maggiore di {min_revision}")
    venues = feed.get("venues")
    if not isinstance(venues, list) or not 0 < len(venues) <= 50000:
        return errors + ["elenco locali vuoto o troppo grande"]
    ids = set()
    for v in venues:
        where = v.get("id") if isinstance(v, dict) else v
        if not isinstance(v, dict):
            errors.append(f"{where}: non è un oggetto")
            continue
        for k in ("id", "name", "city"):
            if not isinstance(v.get(k), str) or not v[k]:
                errors.append(f"{where}: {k} mancante")
        if v.get("id") in ids:
            errors.append(f"{where}: id duplicato")
        ids.add(v.get("id"))
        if not https(v.get("source")):
            errors.append(f"{where}: source non https")
        try:
            datetime.strptime(v.get("checkedOn", ""), "%Y-%m-%d")
        except (TypeError, ValueError):
            errors.append(f"{where}: checkedOn non valido")
        if v.get("outdoors") and not https(v["outdoors"].get("source")):
            errors.append(f"{where}: outdoors.source non https")
        if not isinstance(v.get("dishes"), list) or not v["dishes"]:
            errors.append(f"{where}: nessun piatto")
            continue
        for d in v["dishes"]:
            c = d.get("cents") if isinstance(d, dict) else None
            if not isinstance(d, dict) or not isinstance(d.get("name"), str) or not d["name"]:
                errors.append(f"{where}: piatto senza nome")
            elif not (c is None or (isinstance(c, int) and not isinstance(c, bool) and 0 < c <= 2**53)):
                errors.append(f"{where}/{d['name']}: prezzo non valido")
            elif d.get("aliases") is not None and not (isinstance(d["aliases"], list) and all(isinstance(a, str) for a in d["aliases"])):
                errors.append(f"{where}/{d['name']}: aliases non validi")
            elif (d.get("photoPage") and not https(d["photoPage"])) or (d.get("photoLicenseUrl") and not https(d["photoLicenseUrl"])):
                errors.append(f"{where}/{d['name']}: link foto non https")
    return errors


def report(out, stats, changes, anomalies, missing, added, skipped, blocked, revision):
    L = ["## Prezzi della settimana", "",
         f"Raccolta del {stats['today']} su tutta Italia. Revisione del file: `{revision}`.", "",
         "| | Numero |", "|---|---:|",
         f"| Fonti lette con prezzi | {stats['sources']} |",
         f"| Locali già pubblicati riconfermati | {stats['confirmed']} di {stats['existing']} |",
         f"| Prezzi aggiornati | {len(changes)} |",
         f"| Prezzi anomali (non applicati) | {len(anomalies)} |",
         f"| Locali nuovi | {len(added)} |",
         f"| Città nuove | {stats['new_cities']} |",
         f"| Totale locali dopo la PR | {stats['total']} |",
         f"| Totale prezzi dopo la PR | {stats['dishes']} |", ""]
    if blocked:
        L += ["> ⚠️ Cambiavano troppi prezzi in una volta: nessun cambio applicato, sono tutti tra le anomalie. "
              "Di solito vuol dire che un sito ha cambiato impaginazione.", ""]
    if anomalies:
        L += ["### Da controllare a mano (prezzo vecchio lasciato)", "", "| Locale | Piatto | Prima | Trovato | Motivo |", "|---|---|---:|---|---|"]
        for v, d, old, new, why in anomalies[:80]:
            L.append(f"| {v['name']} ({v['city']}) | {d['name']} | {euro(old) if old else '–'} | {', '.join(euro(n) for n in new)} | {why} |")
        if len(anomalies) > 80:
            L.append(f"| … altre {len(anomalies) - 80} | | | | |")
        L.append("")
    if changes:
        L += ["### Prezzi aggiornati", "", "| Locale | Piatto | Prima | Ora |", "|---|---|---:|---:|"]
        for v, d, old, new in changes[:80]:
            L.append(f"| {v['name']} ({v['city']}) | {d['name']} | {euro(old)} | {euro(new)} |")
        L.append("")
    if added:
        by_city = Counter(v["city"] for v in added)
        L += ["### Locali nuovi", "", "Segnati con `\"origin\": \"raccolta-automatica\"` in menus.json.", "",
              "| Locale | Città | Piatti | Esempio | Fonte |", "|---|---|---:|---|---|"]
        for v in sorted(added, key=lambda v: (v["city"], v["name"]))[:150]:
            ex = v["dishes"][len(v["dishes"]) // 2]
            L.append(f"| {v['name']} | {v['city']} | {len(v['dishes'])} | {ex['name']} {euro(ex['cents'])} | [link]({v['source']}) |")
        L += ["", "Città: " + ", ".join(f"{c} ({n})" for c, n in by_city.most_common()), ""]
    if missing:
        L += ["### Locali pubblicati in cui la fonte non mostra più la maggior parte dei piatti", ""]
        L += [f"- {v['name']} ({v['city']}): {found} di {len(v['dishes'])} piatti ritrovati, [fonte]({v['source']})" for v, found in missing[:40]]
        L.append("")
    if skipped:
        L += ["<details><summary>Fonti scartate per i locali nuovi</summary>", "", "| Motivo | Numero |", "|---|---:|"]
        L += [f"| {k} | {n} |" for k, n in skipped.most_common()]
        L += ["", "</details>", ""]
    L += ["Nessun locale o piatto è stato cancellato. I controlli dell'app su menus.json sono passati."]
    text = "\n".join(L)
    out.write_text(text[:60000], encoding="utf-8")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("results", type=Path, help="cartella con gli artifact fonti-* e documenti-*")
    cli.add_argument("--menus", type=Path, default=Path("menus.json"))
    cli.add_argument("--dataset", type=Path, default=Path("dati-italia.zip"))
    cli.add_argument("--report", type=Path, default=Path("riassunto-prezzi.md"))
    cli.add_argument("--new-limit", type=int, default=300)
    cli.add_argument("--min-revision", type=int, default=BUNDLE_REVISION)
    cli.add_argument("--app", type=Path, default=Path("app.html"), help="pagina dell'app da cui leggere la revisione del bundle")
    cli.add_argument("--today", default=datetime.now(timezone.utc).date().isoformat())
    args = cli.parse_args()

    args.min_revision = max(args.min_revision, bundle_revision(args.app))
    feed = json.loads(args.menus.read_text(encoding="utf-8"))
    before = json.dumps(feed, ensure_ascii=False, sort_keys=True)
    venues = feed["venues"]
    old_cities = {v["city"] for v in venues}
    sources = load_sources(args.results)
    changes, anomalies, confirmed, missing, blocked = update_existing(venues, sources, args.today)
    rows, places = dataset_lookup(args.dataset)
    added, skipped = new_venues(sources, venues, rows, places, args.today, args.new_limit)
    venues.extend(added)

    # Anche senza novità, una revisione non più alta di quella dell'app va alzata, altrimenti l'app ignora il file.
    changed = json.dumps(feed, ensure_ascii=False, sort_keys=True) != before or feed.get("revision", 0) <= args.min_revision
    if changed:
        day = int(args.today.replace("-", "")) * 100
        feed["revision"] = max(feed.get("revision", 0) + 1, day + 1, args.min_revision + 1)
    errors = valid_feed(feed, args.min_revision)
    if errors:
        print("menus.json non passerebbe i controlli dell'app:", *errors[:50], sep="\n- ", file=sys.stderr)
        sys.exit(1)
    stats = {"today": args.today, "sources": sum(1 for s in sources.values() if s["items"]),
             "confirmed": confirmed, "existing": len(venues) - len(added), "total": len(venues),
             "dishes": sum(len(v["dishes"]) for v in venues),
             "new_cities": len({v["city"] for v in added} - old_cities)}
    if changed:
        args.menus.write_text(json.dumps(feed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    report(args.report, stats, changes, anomalies, missing, added, skipped, blocked, feed["revision"])
    print(json.dumps({"cambiato": changed, "prezzi_aggiornati": len(changes), "anomalie": len(anomalies),
                      "locali_nuovi": len(added), "revision": feed["revision"]}))
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            print(f"changed={'true' if changed else 'false'}", file=f)
            print(f"revision={feed['revision']}", file=f)


if __name__ == "__main__":
    main()

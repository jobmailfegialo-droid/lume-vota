"""Rilegge PDF e immagini già individuati, conservando solo voci/prezzi candidati e relativa pagina."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from raccogli_menu import HostPolicy, clean, cents, dish_name, extract_prices, public_url

END_AMOUNT = re.compile(r"^(?P<name>.+?)(?:\s{2,}|\.{2,})\s*(?:€\s*)?(?P<price>\d{1,3}[,.]\d{2})\s*(?:€)?\s*$")
# Nei menu impaginati il prezzo è spesso un intero o con un decimale, staccato dal nome da più spazi o puntini.
END_INTERO = re.compile(r"^(?P<name>[^\d€]*[A-Za-zÀ-ÿ][^€]*?)(?:\s{2,}|\s*\.{3,}\s*)(?:€\s*)?(?P<price>\d{1,3}(?:[,.]\d{1,2})?)\s*(?:€)?\s*$")
PREZZO_SOLO = re.compile(r"(?:€\s*)?\d{1,3}(?:[,.]\d{1,2})?(?:\s*€)?")
SKIP_UNIT = re.compile(r"(?:/|\bal(?:l[ao]|l[’'])?)\s*(?:kg|hg|etto|100\s*g|persona|pezzo)\b|(?:per|min\.?)\s*\d+\s*(?:persone|pezzi)",re.I)

def segmenti(raw):
    """Una riga impaginata su più colonne ("Margherita   7      Diavola   8") diventa più coppie nome-prezzo."""
    pezzi=[p for p in re.split(r"\s{4,}",raw.strip()) if p]
    if len(pezzi)<=2:return [raw]
    uniti,i=[],0
    while i<len(pezzi):
        if i+1<len(pezzi) and not PREZZO_SOLO.fullmatch(pezzi[i]) and PREZZO_SOLO.fullmatch(pezzi[i+1]):
            uniti.append(pezzi[i]+"   "+pezzi[i+1]);i+=2
        else:uniti.append(pezzi[i]);i+=1
    return uniti

def rows(text,method):
    found={}
    for riga in text.splitlines():
        if SKIP_UNIT.search(riga):continue
        for raw in segmenti(riga):
            explicit=extract_prices([clean(raw)],[])
            matched=END_AMOUNT.fullmatch(raw.strip()) or END_INTERO.fullmatch(raw.strip())
            candidates=explicit
            if not candidates and matched:
                name=dish_name(matched["name"]);price=cents(matched["price"])
                if name and price:candidates=[{"name":name,"cents":price}]
            for item in candidates:
                found[item["name"].lower(),item["cents"]]={"name":item["name"],"cents":item["cents"],"method":method}
    return list(found.values())

def run(cmd,timeout=30):
    env={**os.environ,"OMP_THREAD_LIMIT":"1"}
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,timeout=timeout)
    return p.stdout.decode("utf-8","replace") if p.returncode==0 else ""

def inspect(source,policy):
    result={**source,"pages":[]}
    try:
        final,kind,_,data=policy.fetch(source["url"])
        result["url"]=final
        result["sha256"]=hashlib.sha256(data).hexdigest()
        pdf=data.startswith(b"%PDF")
        if not pdf and not kind.startswith("image/"):raise ValueError("formato cambiato")
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/("menu.pdf" if pdf else "menu.img");file.write_bytes(data)
            if pdf:
                info=run(["pdfinfo",str(file)])
                count=re.search(r"^Pages:\s+(\d+)",info,re.M)
                if not count:raise ValueError("PDF illeggibile")
                total=int(count[1])
            else:total=1
            result["pagine_totali"]=total
            for page in range(1,min(8,total)+1):
                items=[]
                if pdf:
                    visible=run(["pdftotext","-f",str(page),"-l",str(page),"-layout",str(file),"-"])
                    items=rows(visible,"pdf_testo_allineato")
                if not items and page<=4:
                    image=file
                    if pdf:
                        prefix=Path(tmp)/"pagina"
                        run(["pdftoppm","-f",str(page),"-l",str(page),"-scale-to","1800","-singlefile","-png",str(file),str(prefix)])
                        image=prefix.with_suffix(".png")
                    if image.exists():
                        text=run(["tesseract",str(image),"stdout","-l","ita+eng","--psm","6","-c","preserve_interword_spaces=1"])
                        items=rows(text,"ocr_riga")
                result["pages"].append({"page":page,"candidates":items[:220]})
        result["status"]="prezzi_candidati" if any(p["candidates"] for p in result["pages"]) else "revisione_visiva"
    except (OSError,ValueError,subprocess.TimeoutExpired) as err:result["status"]="non_accessibile";result["reason"]=type(err).__name__
    return result

def main():
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument("input",type=Path);cli.add_argument("output",type=Path)
    cli.add_argument("--part",type=int,default=0);cli.add_argument("--parts",type=int,default=1)
    args=cli.parse_args()
    for binary in ("pdftotext","pdftoppm","pdfinfo","tesseract"):
        if not shutil.which(binary):cli.error(binary+" non disponibile")
    docs={}
    for file in args.input.rglob("esiti.ndjson"):
        for line in file.open():
            row=json.loads(line)
            for page in row.get("pages",[]):
                if page["type"]=="pdf" or page["type"].startswith("image/"):
                    url=public_url(page["url"])
                    if not url:continue
                    src=docs.setdefault(url,{"url":url,"type":page["type"],"venues":[]})
                    src["venues"].append({"id":row["id"],"name":row["name"],"city":row["city"]})
                    src["venues"].extend(row.get("altre_sedi",[]))
    from raccogli_menu import domain
    tasks=[r for u,r in docs.items() if int(hashlib.sha256(domain(u).encode()).hexdigest(),16)%args.parts==args.part]
    counts=Counter();policy=HostPolicy();args.output.mkdir(exist_ok=True,parents=True)
    with (args.output/"documenti.ndjson").open("w") as out, ThreadPoolExecutor(4) as pool:
        for future in as_completed([pool.submit(inspect,t,policy) for t in tasks]):
            record=future.result()
            counts["documenti"]+=1;counts[record["status"]]+=1
            counts["coppie_candidate"]+=sum(len(p["candidates"]) for p in record["pages"])
            print(json.dumps(record,ensure_ascii=False),file=out,flush=True)
    (args.output/"totali.json").write_text(json.dumps(counts))
    print("RISULTATO",dict(counts))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a") as s:print(dict(counts),file=s)
if __name__=="__main__":main()

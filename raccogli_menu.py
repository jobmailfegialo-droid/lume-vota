"""Ricerca nazionale di fonti e prezzi. I candidati con prezzo restano distinti dal catalogo verificato."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
from threading import Lock
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request
from urllib.robotparser import RobotFileParser
from zipfile import ZipFile

AGENT = "LumeMenu/1.0 (+https://github.com/jobmailfegialo-droid/lume-vota)"
SOCIAL = {"facebook.com","instagram.com","tripadvisor.it","tripadvisor.com","google.com","goo.gl","google.it","tiktok.com","twitter.com","x.com","whatsapp.com","wa.me","linktr.ee","youtu.be","youtube.com"}
BLOCKS = set("p br div li tr td section article h1 h2 h3 h4 h5 h6 dt dd figure".split())
MENU_WORD = re.compile(r"\b(menu|menù|carta|listino|speisekarte)\b",re.I)
BAD_NAME = re.compile(r"\b(coperto|minimo|a partire|al kg|all.etto|all.hg|al pezzo|supplemento|delivery|consegna|sconto|prezzo|totale|minimum|aggiunta|servizio|privacy|cookie|iva|spese|prenota|carrello)\b",re.I)
TARIFF = re.compile(r"(?:€|EUR)\s*(\d{1,3}(?:[.,]\d{1,2})?)|(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:€|EUR)",re.I)
MENU_PATH = re.compile(r"\.(pdf|jpeg|jpg|png|webp)$",re.I)
CANDIDATE_LIMIT = 320

def clean(text):
    return " ".join(str(text or "").split())

def domain(url):
    try: return (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError: return ""

def public_url(url):
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if (parts.scheme not in ("http","https") or not host or "." not in host or parts.username or parts.password
            or parts.port not in (None,80,443) or len(url)>1400 or host.endswith((".local",".internal",".localhost"))
            or any(domain(url)==s or domain(url).endswith("."+s) for s in SOCIAL)): return ""
        if re.search(r"(?:token|api_key|sessionid|signature|password)=",parts.query,re.I): return ""
        if any(c.isspace() or ord(c)<32 for c in url) or "\\" in url: return ""
        try:
            if not ipaddress.ip_address(host).is_global: return ""
        except ValueError: pass
        return urlunsplit((parts.scheme,parts.netloc,parts.path or "/",parts.query,""))
    except ValueError: return ""

@lru_cache(maxsize=40000)
def public_host(host):
    ips = socket.getaddrinfo(host,None,type=socket.SOCK_STREAM)
    return bool(ips) and all(ipaddress.ip_address(x[4][0]).is_global for x in ips)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args): return None

def request(url, limit):
    if not public_url(url) or not public_host(urlsplit(url).hostname): raise ValueError("indirizzo escluso")
    req = Request(url,headers={"User-Agent":AGENT,"Accept":"text/html,application/xhtml+xml,application/pdf,image/*;q=0.8,*/*;q=0.3"})
    with build_opener(NoRedirect()).open(req,timeout=7) as page:
        body = page.read(limit+1)
        if len(body)>limit: raise ValueError("risorsa troppo grande")
        return page.headers.get_content_type(),page.headers.get_content_charset() or "utf-8",body

class HostPolicy:
    def __init__(self):
        self.locks = defaultdict(Lock)
        self.rules, self.last = {}, {}
        self.guard = Lock()
    def load(self, root):
        rules = RobotFileParser()
        try:
            url=root+"/robots.txt"
            for _ in range(5):
                try:
                    _,_,data = request(url,512000)
                    rules.parse(data.decode("utf-8","replace").splitlines())
                    break
                except HTTPError as redirect:
                    if redirect.code not in (301,302,303,307,308) or not redirect.headers.get("Location"):raise
                    url=urljoin(url,redirect.headers["Location"])
            else: rules.disallow_all=True
        except HTTPError as err:
            if err.code in (404,410): rules.allow_all = True
            else: rules.disallow_all = True
        except (OSError,ValueError): rules.disallow_all = True
        return rules
    def fetch(self,url):
        for _ in range(5):
            if not public_url(url): raise ValueError("indirizzo escluso")
            parts = urlsplit(url)
            host = domain(url)
            root = parts.scheme+"://"+parts.netloc
            with self.guard: lock = self.locks[host]
            with lock:
                if root not in self.rules: self.rules[root] = self.load(root)
                rules = self.rules[root]
                if not rules.can_fetch(AGENT,url): raise ValueError("robots o sito indisponibile")
                delay = max(1,rules.crawl_delay("LumeMenu") or rules.crawl_delay("*") or 0)
                rate = rules.request_rate("LumeMenu") or rules.request_rate("*")
                if rate and rate.requests: delay = max(delay,rate.seconds/rate.requests)
                if delay>15: raise ValueError("rimandato per intervallo richiesto")
                time.sleep(max(0,self.last.get(host,0)+delay-time.monotonic()))
                self.last[host] = time.monotonic()
                try: return (url,*request(url,6_000_000))
                except HTTPError as err:
                    if err.code in (301,302,303,307,308) and err.headers.get("Location"):
                        url = urljoin(url,err.headers["Location"])
                    else:
                        if err.code==429: self.rules[root].disallow_all=True
                        raise
        raise ValueError("troppi reindirizzamenti")

class MenuHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines,self.links,self.structured = [],[],[]
        self.parts,self.anchor,self.ld = [],None,None
        self.skip = 0
    def flush(self):
        line=clean(" ".join(self.parts))
        if line:self.lines.append(line)
        self.parts=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ("script","style","noscript"):
            self.skip+=1
            if tag=="script" and (a.get("type") or "").lower()=="application/ld+json": self.ld=[]
        if self.skip:return
        if tag in BLOCKS:self.flush()
        if tag=="a":self.anchor=[a.get("href") or "",[]]
        if tag=="img":
            href=a.get("data-src") or a.get("src") or ""
            if MENU_WORD.search((a.get("alt") or "")+" "+href.replace("-"," ")):self.links.append((href,"menu immagine"))
    def handle_data(self,text):
        if self.ld is not None: self.ld.append(text)
        if self.skip:return
        self.parts.append(text)
        if self.anchor:self.anchor[1].append(text)
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript"):
            if tag=="script" and self.ld is not None:
                try: self.structured.append(json.loads("".join(self.ld)))
                except (ValueError,RecursionError): pass
                self.ld=None
            self.skip=max(0,self.skip-1)
        if self.skip:return
        if tag=="a" and self.anchor:
            self.links.append((self.anchor[0],clean(" ".join(self.anchor[1]))));self.anchor=None
        if tag in BLOCKS:self.flush()

def cents(text):
    try:
        value=Decimal(str(text).replace(",","."))
        if value.is_finite() and 0 < value <= 500 and value*100 == (value*100).to_integral_value(): return int(value*100)
    except (ValueError,ArithmeticError): pass

def dish_name(raw):
    name=clean(raw).strip(" \t•:–—.-")
    if not 3<=len(name)<=90 or not any(c.isalpha() for c in name) or BAD_NAME.search(name) or re.search(r"€|https?://|\d\s*(kg|hg|persone)\b",name,re.I):return ""
    return name

def extract_prices(lines,structured):
    found={}
    def add(name,price,method):
        name=dish_name(name)
        if name and price:found.setdefault((name.casefold(),price),{"name":name,"cents":price,"method":method})
    stack=list(structured)
    while stack:
        node=stack.pop()
        if isinstance(node,list):stack.extend(node)
        if not isinstance(node,dict):continue
        stack.extend(n for n in node.values() if isinstance(n,(dict,list)))
        types=node.get("@type",[])
        if "MenuItem" not in (types if isinstance(types,list) else [types]):continue
        offers=node.get("offers") or []
        for offer in (offers if isinstance(offers,list) else [offers]):
            if isinstance(offer,dict) and str(offer.get("priceCurrency","")).upper()=="EUR":
                add(node.get("name"),cents(offer.get("price")),"schema_menuitem")
    for i,line in enumerate(lines):
        matches=list(TARIFF.finditer(line))
        if len(matches)!=1: continue
        price=matches[0]
        if line[price.end():].strip(" ."):continue
        name=line[:price.start()].strip(" .·\t–—-")
        method="stessa_riga"
        if not name and i>0:
            name=lines[i-1];method="riga_precedente"
        add(name,cents(price.group(1) or price.group(2)),method)
    return list(found.values())[:CANDIDATE_LIMIT]

def menu_links(page,base):
    ranked={}
    for href,label in page.links:
        if not href or href.startswith(("#","mailto:","tel:")):continue
        url=public_url(urljoin(base,href))
        if not url or url==base:continue
        path=urlsplit(url).path
        words=re.sub(r"[_/.-]"," ",path)
        if not (MENU_WORD.search(label) or MENU_WORD.search(words)):continue
        if domain(url)!=domain(base) and not MENU_WORD.search(label):continue
        if re.search(r"cookie|privacy|allergen|javascript:|traduz|/wp-admin|login",path,re.I):continue
        score=8*bool(MENU_WORD.search(label))+4*bool(MENU_PATH.search(path))+2*bool(MENU_WORD.search(words))
        ranked[url]=max(score,ranked.get(url,0))
    return sorted(ranked,key=lambda k:(-ranked[k],len(k)))[:3]

def read_page(fetch,url,is_menu):
    final,kind,encoding,body=fetch(url)
    entry={"url":final,"type":kind,"candidates":[]}
    if body.startswith(b"%PDF") or kind=="application/pdf":
        entry["type"]="pdf"
        if shutil.which("pdftotext"):
            output=subprocess.run(["pdftotext","-layout","-","-"],input=body,capture_output=True,timeout=12)
            lines=[clean(x) for x in output.stdout.decode("utf-8","replace").splitlines() if clean(x)]
            entry["candidates"]=extract_prices(lines,[])
        return entry,[]
    if kind.startswith("image/"):return entry,[]
    if kind not in ("text/html","application/xhtml+xml","text/plain"):return None,[]
    try:html=body.decode(encoding,errors="replace")
    except LookupError:html=body.decode("utf-8",errors="replace")
    page=MenuHTML();page.feed(html);page.flush()
    entry["candidates"]=extract_prices(page.lines if is_menu else [],page.structured)
    return entry,menu_links(page,final)

def collect(seed,policy):
    direct,site=seed["menu"],seed["site"]
    result={"id":seed["id"],"name":seed["name"],"city":seed["city"],"kind":seed["kind"],
            "localita":seed["localita"],"provincia":seed["provincia"],"regione":seed["regione"],"pages":[]}
    try:
        start=direct or site
        page,links=read_page(policy.fetch,start,bool(direct))
        if page and (direct or page["candidates"] or page["type"]=="pdf"):result["pages"].append(page)
        if not page or not page["candidates"]:
            for link in links[:2]:
                try:
                    child,_=read_page(policy.fetch,link,True)
                    if child:result["pages"].append(child)
                except (ValueError,OSError,subprocess.TimeoutExpired):continue
        result["status"]="prezzi_candidati" if any(p["candidates"] for p in result["pages"]) else "fonte_da_verificare" if result["pages"] else "nessun_menu"
    except (ValueError,OSError,subprocess.TimeoutExpired) as err:
        result["status"]="http_"+str(err.code) if isinstance(err,HTTPError) else "non_accessibile"
    return result

def seeds(archive,mode,regione=None):
    from geografia import Territorio,righe
    territorio=Territorio(archive)
    for r in righe(archive):
        menu,site=public_url(r[12]),public_url(r[9])
        if (mode=="diretti" and not menu) or (mode=="siti" and (menu or not site)) or not(menu or site):continue
        localita,provincia,reg=territorio.luogo(r)
        if regione and reg!=regione:continue
        yield {"id":r[0],"name":r[3],"kind":r[4],"city":r[6] or localita,"localita":localita,"provincia":provincia,"regione":reg,"menu":menu,"site":site}

def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--dataset",default="dati-italia.zip")
    cli.add_argument("--mode",choices=["diretti","siti","tutti"],default="diretti")
    cli.add_argument("--parts",type=int,default=1);cli.add_argument("--part",type=int,default=0)
    cli.add_argument("--regione",help="Solo i locali di questa regione, es. Lombardia")
    cli.add_argument("--workers",type=int,default=6);cli.add_argument("--limit",type=int)
    cli.add_argument("--output",type=Path,default=Path("raccolta"))
    args=cli.parse_args()
    if not 1<=args.workers<=12 or not 0<=args.part<args.parts:cli.error("Partizione o concorrenza non valida")
    queue=[r for r in seeds(args.dataset,args.mode,args.regione) if int(hashlib.sha256(domain(r["menu"] or r["site"]).encode()).hexdigest(),16)%args.parts==args.part]
    queue.sort(key=lambda x:(not x["menu"],x["kind"]!="restaurant",x["id"]))
    if args.limit is not None:queue=queue[:args.limit]
    args.output.mkdir(exist_ok=True,parents=True);counts=Counter();policy=HostPolicy()
    date=datetime.now(timezone.utc).date().isoformat()
    with (args.output/"esiti.ndjson").open("w") as file, ThreadPoolExecutor(args.workers) as pool:
        groups=defaultdict(list)
        for seed in queue: groups[seed["menu"] or seed["site"]].append(seed)
        tasks={pool.submit(collect,group[0],policy):group for group in groups.values()}
        for i,task in enumerate(as_completed(tasks),1):
            group=tasks[task]
            try: row=task.result()
            except Exception as e:row={**{k:group[0][k] for k in ("id","name","city","kind","localita","provincia","regione")},"status":"errore_lettura","pages":[],"reason":type(e).__name__}
            if len(group)>1:
                row["altre_sedi"]=[{k:r[k] for k in ("id","name","city","localita","provincia")} for r in group[1:]]
                row["fonte_condivisa"]=True
            row["checkedOn"]=date
            print(json.dumps(row,ensure_ascii=False),file=file,flush=True)
            counts[row["status"]]+=1
            counts["schede"]+=len(group)
            counts["url_iniziali_distinti"]+=1
            counts["coppie_piatto_prezzo"]+=sum(len(p["candidates"]) for p in row["pages"])
            if i%100==0: print("Controllate",i,"di",len(queue),dict(counts),flush=True)
    (args.output/"totali.json").write_text(json.dumps(counts))
    with ZipFile(args.dataset) as archive:
        (args.output/"LICENSE-OSM.md").write_bytes(archive.read("LICENSE.md"))
    print("RISULTATO",json.dumps(counts),flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a") as summary:print("### "+(args.regione or "Partizione "+str(args.part)),"\n\n|Esito|Numero|\n|---|---:|",file=summary);print("\n".join(f"|{k}|{v}|" for k,v in counts.items()),file=summary)
if __name__=="__main__":main()

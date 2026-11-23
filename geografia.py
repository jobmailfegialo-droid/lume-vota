"""Località, provincia e regione di ogni locale della guida, senza dipendenze esterne.

Un locale con il comune indicato in OpenStreetMap (addr:city) prende quella località.
Gli altri prendono la località più vicina, pesata sulla popolazione: un quartiere di una
grande città resta nella città, un locale in campagna va alla frazione accanto.
"""
import json
from functools import lru_cache
from math import cos, radians, sqrt
from pathlib import Path
from zipfile import ZipFile
import unicodedata

ROOT = Path(__file__).resolve().parent
QUARTIERE = 3  # tipo di località in settlements.json: 0 città, 1 cittadina, 2 paese, 3 quartiere, 4 frazione

def chiave(text):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())

def righe(archive):
    """Righe della guida come liste di 13 campi (id, lat, lon, nome, tipo, cucina, città, indirizzo, telefono, sito, orari, servizi, menu)."""
    with ZipFile(archive) as z: cells = json.loads(z.read("cells.json"))
    for block in cells.values():
        for line in block.splitlines():
            if line: yield (line.split("\t") + [""] * 13)[:13]

class Territorio:
    def __init__(self, archive=ROOT / "dati-italia.zip", territorio=ROOT / "dati" / "territorio.json"):
        with ZipFile(archive) as z: self.localita = json.loads(z.read("settlements.json"))
        data = json.loads(Path(territorio).read_text())
        self.province, self.sigle = data["province"], data["localita"]
        self.griglia, self.per_nome = {}, {}
        for i, (name, lat, lon, kind, _, _) in enumerate(self.localita):
            self.per_nome.setdefault(chiave(name), []).append(i)
            if kind != QUARTIERE: self.griglia.setdefault((lat // 10000, lon // 10000), []).append(i)

    def _vicine(self, lat, lon, raggio=1):
        a, b = lat // 10000, lon // 10000
        for da in range(-raggio, raggio + 1):
            for db in range(-raggio, raggio + 1): yield from self.griglia.get((a + da, b + db), ())

    @staticmethod
    def _distanza(lat, lon, place):
        dy = (lat - place[1]) * 1.112; dx = (lon - place[2]) * 1.112 * cos(radians(lat / 1e5))
        return sqrt(dx * dx + dy * dy) / 1000  # km

    @staticmethod
    def _raggio(place):
        return 0.6 + 0.3 * sqrt(max(place[5], 0) / 1000)  # km; Milano ~ 11,7 km, frazione di 200 abitanti ~ 0,7 km

    def indice(self, lat, lon, citta=""):
        lat, lon = int(lat), int(lon)
        if citta:
            omonime = self.per_nome.get(chiave(citta), ())
            vicine = [i for i in omonime if self._distanza(lat, lon, self.localita[i]) < 30]
            if vicine: return min(vicine, key=lambda i: self._distanza(lat, lon, self.localita[i]))
        best, score = None, None
        for raggio in (1, 3):
            for i in self._vicine(lat, lon, raggio):
                p = self.localita[i]; s = self._distanza(lat, lon, p) / self._raggio(p)
                if score is None or s < score: best, score = i, s
            if best is not None: return best
        return None

    def luogo(self, riga):
        """(località, sigla provincia, regione) di una riga della guida."""
        i = self.indice(riga[1], riga[2], riga[6])
        if i is None: return riga[6] or "", "", ""
        sigla = self.sigle[i]
        return self.localita[i][0], sigla, self.province[sigla]["regione"]

    def regioni(self):
        return sorted({p["regione"] for p in self.province.values()})

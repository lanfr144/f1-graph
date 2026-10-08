"""Extrait les données F1 de l'API Jolpica-F1 (successeur d'Ergast) vers un cache local.

Chaque page de réponse est enregistrée telle quelle sous donnees/brut/, avec à
côté un fichier .meta.json (URL, date, SHA-256). charger.py ne lit que ce cache :
le chargement ne touche jamais le réseau, et un rechargement ne coûte aucune requête.

Limites de l'API sans jeton : 4 requêtes/s en rafale, 500 requêtes/heure.
L'extraction complète (1950 à aujourd'hui, sans tours ni arrêts) en demande
environ 700 : comptez un peu plus d'une heure, interruptible et reprise à
l'identique grâce au cache.

    python extraire.py                       # toutes les saisons, données de base
    python extraire.py --de 2020 --a 2024    # un intervalle
    python extraire.py --de 2011 --arrets    # + arrêts au stand (données depuis 2011)
    python extraire.py --de 2024 --tours     # + temps au tour (lourd : ~15 pages par course)

La saison en cours est toujours re-téléchargée (ses résultats évoluent) ; les
saisons closes ne le sont qu'avec --forcer.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

from commun import API, TAILLE_PAGE, USER_AGENT, dossier_cache, fichier_page, lire_pages


class Limiteur:
    """Fenêtre glissante : au plus `par_heure` requêtes sur 3600 s, et un intervalle minimal."""

    def __init__(self, par_heure: int, intervalle: float) -> None:
        self.par_heure = par_heure
        self.intervalle = intervalle
        self.instants: deque[float] = deque()

    def attendre(self) -> None:
        maintenant = time.monotonic()
        while self.instants and maintenant - self.instants[0] >= 3600:
            self.instants.popleft()
        if len(self.instants) >= self.par_heure:
            pause = 3600 - (maintenant - self.instants[0]) + 1
            reprise = dt.datetime.now() + dt.timedelta(seconds=pause)
            print(f"  quota horaire atteint ({self.par_heure} requêtes) : "
                  f"pause jusqu'à {reprise:%H:%M:%S}", flush=True)
            time.sleep(pause)
        if self.instants:
            ecart = time.monotonic() - self.instants[-1]
            if ecart < self.intervalle:
                time.sleep(self.intervalle - ecart)
        self.instants.append(time.monotonic())


class Extracteur:
    def __init__(self, limiteur: Limiteur) -> None:
        self.limiteur = limiteur
        self.requetes = 0

    def _get(self, url: str) -> bytes:
        for tentative in range(1, 7):
            self.limiteur.attendre()
            self.requetes += 1
            requete = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                           "Accept": "application/json"})
            try:
                with urllib.request.urlopen(requete, timeout=60) as reponse:
                    return reponse.read()
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    attente = int(e.headers.get("Retry-After") or 0) or min(30 * 2 ** (tentative - 1), 900)
                    print(f"  HTTP {e.code} sur {url} : nouvel essai dans {attente} s", flush=True)
                    time.sleep(attente)
                    continue
                raise SystemExit(f"HTTP {e.code} sur {url} : {e.reason}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                attente = min(30 * 2 ** (tentative - 1), 900)
                print(f"  erreur réseau ({e}) sur {url} : nouvel essai dans {attente} s", flush=True)
                time.sleep(attente)
        raise SystemExit(f"Abandon après 6 tentatives : {url}")

    def _page(self, chemin_api: str, offset: int) -> dict:
        url = f"{API}{chemin_api}.json?" + urllib.parse.urlencode({"limit": TAILLE_PAGE, "offset": offset})
        corps = self._get(url)
        try:
            donnees = json.loads(corps)
            mr = donnees["MRData"]
        except (ValueError, KeyError) as e:
            raise SystemExit(f"Réponse inattendue (pas de MRData) pour {url}") from e
        fichier = fichier_page(chemin_api, offset)
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_bytes(corps)
        fichier.with_suffix(".meta.json").write_text(json.dumps({
            "url": url,
            "recupere_le": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "sha256": hashlib.sha256(corps).hexdigest(),
            "octets": len(corps),
        }, indent=2), encoding="utf-8")
        return mr

    def recuperer(self, chemin_api: str, forcer: bool) -> list[dict]:
        """Toutes les pages d'un point d'accès ; depuis le cache s'il est complet."""
        pages = lire_pages(chemin_api)
        if pages and not forcer:
            total = int(pages[0]["total"])
            if len(pages) == max(1, math.ceil(total / TAILLE_PAGE)):
                return pages
        if forcer and dossier_cache(chemin_api).exists():
            # Repartir de zéro : des pages surnuméraires d'un ancien total resteraient sinon.
            shutil.rmtree(dossier_cache(chemin_api))
        premiere = self._page(chemin_api, 0)
        pages = [premiere]
        total = int(premiere["total"])
        for offset in range(TAILLE_PAGE, total, TAILLE_PAGE):
            pages.append(self._page(chemin_api, offset))
        print(f"  {chemin_api} : {total} élément(s), {len(pages)} page(s)", flush=True)
        return pages


def courses(pages: list[dict]) -> list[dict]:
    return [r for p in pages for r in p["RaceTable"]["Races"]]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--de", type=int, help="première saison (défaut : la plus ancienne)")
    p.add_argument("--a", type=int, help="dernière saison (défaut : la plus récente)")
    p.add_argument("--arrets", action="store_true", help="extraire les arrêts au stand (1 requête par course)")
    p.add_argument("--tours", action="store_true", help="extraire les temps au tour (~15 requêtes par course)")
    p.add_argument("--forcer", action="store_true", help="re-télécharger même les saisons closes")
    p.add_argument("--par-heure", type=int, default=480,
                   help="plafond horaire de requêtes (défaut 480, sous la limite de 500 de l'API)")
    args = p.parse_args()

    ex = Extracteur(Limiteur(args.par_heure, intervalle=0.5))
    aujourd_hui = dt.date.today()

    # Référentiels globaux : toujours rafraîchis (un nouveau pilote peut apparaître).
    saisons = [int(s["season"]) for page in ex.recuperer("seasons", forcer=True)
               for s in page["SeasonTable"]["Seasons"]]
    if not saisons:
        raise SystemExit("L'API ne renvoie aucune saison : abandon.")
    saison_en_cours = max(saisons)
    for chemin in ("circuits", "drivers", "constructors", "status"):
        ex.recuperer(chemin, forcer=True)

    debut = args.de or min(saisons)
    fin = args.a or saison_en_cours
    retenues = [s for s in saisons if debut <= s <= fin]
    if not retenues:
        raise SystemExit(f"Aucune saison connue de l'API entre {debut} et {fin}.")

    for saison in retenues:
        forcer = args.forcer or saison == saison_en_cours
        print(f"Saison {saison}{' (en cours)' if saison == saison_en_cours else ''}", flush=True)
        calendrier = courses(ex.recuperer(f"{saison}/races", forcer))
        for point in ("results", "qualifying", "sprint", "driverstandings", "constructorstandings"):
            ex.recuperer(f"{saison}/{point}", forcer)
        if args.arrets or args.tours:
            for course in calendrier:
                if dt.date.fromisoformat(course["date"]) > aujourd_hui:
                    continue  # course à venir : rien à extraire
                manche = int(course["round"])
                if args.arrets:
                    ex.recuperer(f"{saison}/{manche}/pitstops", forcer)
                if args.tours:
                    ex.recuperer(f"{saison}/{manche}/laps", forcer)

    print(f"Terminé : {ex.requetes} requête(s) émise(s). Cache : donnees/brut/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

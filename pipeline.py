"""Extraction et chargement complets, relançables : reprend où la dernière exécution s'est arrêtée.

    python pipeline.py                         # toutes les saisons, données de base
    python pipeline.py --arrets-depuis 2011    # + arrêts au stand à partir de 2011
    python pipeline.py --de 2020 --a 2024      # un intervalle de saisons
    python pipeline.py --etat                  # où en est-on ? (n'exécute rien)
    python pipeline.py --recommencer           # ignorer le point de reprise

Le travail est découpé en étapes : référentiels, schéma, puis pour chaque saison
extraction, [arrêts], [tours] et chargement ; enfin contrôles et manifeste.
Chaque étape terminée est inscrite dans donnees/etat.json. Relancé après une
interruption (Ctrl+C, panne réseau, arrêt du poste, Neo4j indisponible), le script
saute les étapes faites et reprend à la première qui ne l'est pas. Une étape en
échec est retentée à la relance ; les étapes qui en dépendent sont « bloquées »,
les autres continuent. Une exécution menée à terme sans erreur est close : la
relance suivante en ouvre une nouvelle (et rafraîchit la saison en cours).

Traces, dans donnees/journaux/ :
  pipeline-AAAAMMJJ-HHMMSS.log   journal détaillé de l'exécution (niveau DEBUG,
                                 traces Python complètes des erreurs)
  avancement.jsonl               un événement JSON par début et fin d'étape,
                                 cumulé d'une exécution à l'autre

Codes de sortie : 0 succès, 1 au moins une étape en échec ou bloquée,
2 traitement concurrent, 130 interruption.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
import traceback
from collections import defaultdict

from commun import DONNEES, ETAT, JOURNAUX, Verrou, lire_pages

log = logging.getLogger("f1.pipeline")


def maintenant() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def duree(secondes: float) -> str:
    secondes = int(secondes)
    h, reste = divmod(secondes, 3600)
    m, s = divmod(reste, 60)
    return f"{h} h {m:02d} min" if h else (f"{m} min {s:02d} s" if m else f"{s} s")


# --- Journaux ------------------------------------------------------------------

def configurer_journaux(verbeux: bool) -> str:
    JOURNAUX.mkdir(parents=True, exist_ok=True)
    fichier = JOURNAUX / f"pipeline-{dt.datetime.now():%Y%m%d-%H%M%S}.log"
    racine = logging.getLogger()
    racine.setLevel(logging.DEBUG)
    f = logging.FileHandler(fichier, encoding="utf-8")
    f.setLevel(logging.DEBUG)
    f.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)-15s %(message)s"))
    c = logging.StreamHandler(sys.stdout)
    c.setLevel(logging.DEBUG if verbeux else logging.INFO)
    c.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    racine.addHandler(f)
    racine.addHandler(c)
    logging.getLogger("neo4j").setLevel(logging.WARNING)  # bavard au niveau DEBUG
    return str(fichier)


def tracer(evenement: str, **champs) -> None:
    """Ajoute une ligne JSON à avancement.jsonl : lisible par un tableau de bord ou jq."""
    ligne = {"horodatage": maintenant(), "evenement": evenement, **champs}
    with open(JOURNAUX / "avancement.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False, default=str) + "\n")


# --- Point de reprise ------------------------------------------------------------

class Etat:
    """donnees/etat.json, réécrit atomiquement après chaque changement d'étape."""

    def __init__(self) -> None:
        self.donnees = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {}

    @property
    def execution(self) -> dict:
        return self.donnees.get("execution", {})

    @property
    def etapes(self) -> dict:
        return self.donnees.setdefault("etapes", {})

    def reprenable(self) -> bool:
        return self.execution.get("statut") in ("en_cours", "interrompue", "terminee_avec_erreurs")

    def ouvrir(self, parametres: dict) -> None:
        ancienne = self.execution
        if ancienne:
            self.donnees.setdefault("historique", []).append(
                {k: ancienne.get(k) for k in ("id", "debut", "fin", "statut")})
        self.donnees["execution"] = {"id": dt.datetime.now().strftime("%Y%m%d-%H%M%S"),
                                     "debut": maintenant(), "fin": None, "statut": "en_cours",
                                     "parametres": parametres, "reprises": 0}
        self.donnees["etapes"] = {}
        self.sauver()

    def reprendre(self, parametres: dict) -> None:
        ex = self.execution
        if ex.get("parametres") != parametres:
            log.warning("Paramètres différents de l'exécution reprise (%s) : les nouveaux "
                        "s'appliquent, les étapes déjà faites restent acquises.", ex.get("parametres"))
            ex["parametres"] = parametres
        ex["statut"] = "en_cours"
        ex["reprises"] = ex.get("reprises", 0) + 1
        ex["fin"] = None
        self.sauver()

    def fait(self, nom: str) -> bool:
        return self.etapes.get(nom, {}).get("statut") == "fait"

    def marquer(self, nom: str, statut: str, **champs) -> None:
        e = self.etapes.setdefault(nom, {})
        e.update(statut=statut, **champs)
        if statut == "en_cours":
            e["tentatives"] = e.get("tentatives", 0) + 1
            e.pop("erreur", None)
        self.sauver()

    def clore(self, statut: str) -> None:
        self.execution.update(statut=statut, fin=maintenant())
        self.sauver()

    def sauver(self) -> None:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        provisoire = ETAT.with_suffix(".json.tmp")
        provisoire.write_text(json.dumps(self.donnees, indent=2, ensure_ascii=False, default=str),
                              encoding="utf-8")
        os.replace(provisoire, ETAT)  # atomique : jamais d'état à moitié écrit


# --- Exécution des étapes --------------------------------------------------------

class Executeur:
    def __init__(self, etat: Etat) -> None:
        self.etat = etat
        self.total = 0  # inconnu tant que la liste des saisons ne l'est pas
        self.rang = 0
        self.durees: dict[str, list[float]] = defaultdict(list)
        self.restantes: dict[str, int] = defaultdict(int)
        self.bilan: dict[str, list[str]] = defaultdict(list)

    def prevoir(self, nom: str) -> None:
        if not self.etat.fait(nom):
            self.restantes[nom.split(":")[0]] += 1

    def estimation(self) -> str:
        """Reste à faire, d'après la durée moyenne des étapes de même nature déjà passées."""
        total, inconnu = 0.0, False
        for nature, n in self.restantes.items():
            if n <= 0:
                continue
            if self.durees[nature]:
                total += n * sum(self.durees[nature]) / len(self.durees[nature])
            else:
                inconnu = True
        if total < 1:
            return " — durée restante pas encore mesurable" if inconnu else ""
        return f" — reste ~{duree(total)}" + (" (+ étapes non encore mesurées)" if inconnu else "")

    def etape(self, nom: str, fonction, prerequis: tuple[str, ...] = ()) -> bool:
        self.rang += 1
        repere = f"[{self.rang}/{self.total or '?'}] {nom}"
        nature = nom.split(":")[0]
        if self.etat.fait(nom):
            log.debug("%s : déjà faite, sautée", repere)
            self.bilan["sautees"].append(nom)
            return True
        self.restantes[nature] -= 1
        manquants = [p for p in prerequis if not self.etat.fait(p)]
        if manquants:
            log.warning("%s : BLOQUÉE, prérequis non satisfait(s) : %s", repere, ", ".join(manquants))
            self.etat.marquer(nom, "bloquee", prerequis_manquants=manquants, le=maintenant())
            tracer("etape_bloquee", execution=self.etat.execution["id"], etape=nom, prerequis=manquants)
            self.bilan["bloquees"].append(nom)
            return False

        log.info("%s …", repere)
        self.etat.marquer(nom, "en_cours", debut=maintenant())
        tracer("etape_debut", execution=self.etat.execution["id"], etape=nom)
        t0 = time.monotonic()
        try:
            detail = fonction() or {}
        except KeyboardInterrupt:
            self.etat.marquer(nom, "interrompue", fin=maintenant())
            tracer("etape_interrompue", execution=self.etat.execution["id"], etape=nom)
            raise
        except (Exception, SystemExit) as e:
            ecoule = time.monotonic() - t0
            message = str(e) or type(e).__name__
            log.error("%s : ÉCHEC après %s — %s", repere, duree(ecoule), message)
            log.debug("Trace complète de l'échec de %s :\n%s", nom, traceback.format_exc())
            self.etat.marquer(nom, "echec", fin=maintenant(), duree_s=round(ecoule, 1),
                              erreur=message, type_erreur=type(e).__name__)
            tracer("etape_echec", execution=self.etat.execution["id"], etape=nom,
                   duree_s=round(ecoule, 1), erreur=message, type_erreur=type(e).__name__)
            self.bilan["echecs"].append(nom)
            return False
        ecoule = time.monotonic() - t0
        self.durees[nature].append(ecoule)
        self.etat.marquer(nom, "fait", fin=maintenant(), duree_s=round(ecoule, 1), detail=detail)
        tracer("etape_fin", execution=self.etat.execution["id"], etape=nom,
               duree_s=round(ecoule, 1), detail=detail)
        resume = ", ".join(f"{k} {v}" for k, v in detail.items())
        log.info("%s : ok en %s%s%s", repere, duree(ecoule), f" ({resume})" if resume else "",
                 self.estimation())
        self.bilan["faites"].append(nom)
        return True


# --- Programme principal -------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--de", type=int, help="première saison (défaut : la plus ancienne)")
    p.add_argument("--a", type=int, help="dernière saison (défaut : la plus récente)")
    p.add_argument("--arrets-depuis", type=int, metavar="ANNEE",
                   help="extraire et charger les arrêts au stand à partir de cette saison (données : 2011)")
    p.add_argument("--tours-depuis", type=int, metavar="ANNEE",
                   help="idem pour les temps au tour (données : 1996 ; ~15 requêtes par course)")
    p.add_argument("--sans-extraction", action="store_true",
                   help="ne rien télécharger : charger le cache tel qu'il est")
    p.add_argument("--sans-chargement", action="store_true", help="extraire seulement, ne pas toucher Neo4j")
    p.add_argument("--recommencer", action="store_true", help="ignorer le point de reprise, tout refaire")
    p.add_argument("--etat", action="store_true", help="afficher l'avancement enregistré et quitter")
    p.add_argument("--par-heure", type=int, default=480, help="plafond horaire de requêtes (défaut 480)")
    p.add_argument("--verbeux", action="store_true", help="afficher aussi le niveau DEBUG à l'écran")
    args = p.parse_args()

    if args.etat:
        return afficher_etat()

    verrou = Verrou()
    try:
        verrou.__enter__()
    except SystemExit as e:  # un autre traitement tourne sur le même répertoire
        print(e.code, file=sys.stderr)
        return 2
    try:
        return executer(args)
    finally:
        verrou.__exit__(None, None, None)


def afficher_etat() -> int:
    if not ETAT.exists():
        print("Aucune exécution enregistrée.")
        return 0
    etat = Etat()
    ex = etat.execution
    compte = defaultdict(int)
    for e in etat.etapes.values():
        compte[e["statut"]] += 1
    print(f"Exécution {ex.get('id')} — {ex.get('statut')} — débutée {ex.get('debut')}"
          f"{' — finie ' + ex['fin'] if ex.get('fin') else ''} — reprise(s) : {ex.get('reprises', 0)}")
    print(f"Paramètres : {ex.get('parametres')}")
    print("Étapes : " + ", ".join(f"{k} {v}" for k, v in sorted(compte.items())))
    for nom, e in etat.etapes.items():
        if e["statut"] in ("echec", "bloquee", "en_cours", "interrompue"):
            print(f"  {e['statut']:11} {nom} {e.get('erreur') or e.get('prerequis_manquants') or ''}")
    return 0


def executer(args) -> int:
    fichier_journal = configurer_journaux(args.verbeux)
    parametres = {k: getattr(args, k) for k in ("de", "a", "arrets_depuis", "tours_depuis",
                                                "sans_extraction", "sans_chargement")}
    etat = Etat()
    if etat.reprenable() and not args.recommencer:
        etat.reprendre(parametres)
        faites = sum(1 for e in etat.etapes.values() if e["statut"] == "fait")
        log.info("REPRISE de l'exécution %s (débutée %s) : %d étape(s) déjà faite(s).",
                 etat.execution["id"], etat.execution["debut"], faites)
    else:
        if args.recommencer and etat.reprenable():
            log.warning("--recommencer : l'exécution %s inachevée est abandonnée.", etat.execution["id"])
        etat.ouvrir(parametres)
        log.info("NOUVELLE exécution %s", etat.execution["id"])
    log.info("Données : %s — journal : %s", DONNEES, fichier_journal)
    tracer("execution_debut", execution=etat.execution["id"], parametres=parametres,
           reprise=etat.execution.get("reprises", 0) > 0)
    t0 = time.monotonic()

    try:
        executeur = derouler(args, etat)
    except SystemExit as e:  # arrêt global motivé (aucune saison, etc.)
        etat.clore("terminee_avec_erreurs")
        log.error("ARRÊT : %s", e.code)
        tracer("execution_fin", execution=etat.execution["id"], statut="arret", erreur=str(e.code))
        return 1
    except KeyboardInterrupt:
        etat.clore("interrompue")
        log.warning("INTERROMPU après %s. Relancer la même commande pour reprendre.",
                    duree(time.monotonic() - t0))
        tracer("execution_fin", execution=etat.execution["id"], statut="interrompue")
        return 130

    b = executeur.bilan
    statut = "terminee" if not (b["echecs"] or b["bloquees"]) else "terminee_avec_erreurs"
    etat.clore(statut)
    log.info("BILAN en %s : %d faite(s), %d sautée(s) (déjà faites), %d en échec, %d bloquée(s).",
             duree(time.monotonic() - t0), len(b["faites"]), len(b["sautees"]),
             len(b["echecs"]), len(b["bloquees"]))
    for nom in b["echecs"]:
        log.error("  échec   : %s — %s", nom, etat.etapes[nom].get("erreur"))
    for nom in b["bloquees"]:
        log.warning("  bloquée : %s", nom)
    if statut != "terminee":
        log.warning("Relancer la même commande pour retenter les étapes en échec et bloquées.")
    tracer("execution_fin", execution=etat.execution["id"], statut=statut,
           faites=len(b["faites"]), echecs=b["echecs"], bloquees=b["bloquees"])
    return 0 if statut == "terminee" else 1


def derouler(args, etat: Etat) -> Executeur:
    # Imports différés : --etat et le refus de verrou ne chargent ni le réseau ni Neo4j.
    import extraire
    import transformer as tr

    extracteur = extraire.Extracteur(extraire.Limiteur(args.par_heure, intervalle=0.5))

    # 1. Référentiels : ils donnent aussi la liste des saisons, d'où le plan.
    def referentiels() -> dict:
        avant = extracteur.requetes
        saisons = extraire.extraire_referentiels(extracteur)
        return {"saisons_connues": len(saisons), "requetes": extracteur.requetes - avant}

    ex = Executeur(etat)
    if not args.sans_extraction:
        ex.etape("extraction:referentiels", referentiels)
    saisons_api = [int(s["season"]) for page in lire_pages("seasons") for s in page["SeasonTable"]["Seasons"]]
    if not saisons_api:
        raise SystemExit("Aucune liste de saisons en cache : l'extraction des référentiels a échoué "
                         "(voir le journal). Relancer quand l'API répond.")
    saison_en_cours = max(saisons_api)
    debut, fin = args.de or min(saisons_api), args.a or saison_en_cours
    saisons = [s for s in saisons_api if debut <= s <= fin]
    if not saisons:
        raise SystemExit(f"Aucune saison connue entre {debut} et {fin}.")

    # 2. Plan complet, pour numéroter et estimer.
    plan: list[str] = ["extraction:referentiels"] if not args.sans_extraction else []
    if not args.sans_chargement:
        plan += ["chargement:schema", "chargement:referentiels"]
    for s in saisons:
        if not args.sans_extraction:
            plan.append(f"extraction:{s}")
            if args.arrets_depuis and s >= args.arrets_depuis:
                plan.append(f"arrets:{s}")
            if args.tours_depuis and s >= args.tours_depuis:
                plan.append(f"tours:{s}")
        if not args.sans_chargement:
            plan.append(f"chargement:{s}")
    if not args.sans_chargement:
        plan.append("controles")
    plan.append("manifeste")

    ex.total = len(plan)
    for nom in plan[ex.rang:]:
        ex.prevoir(nom)
    log.info("Plan : %d saison(s) (%d–%d), %d étape(s), dont %d déjà faite(s).",
             len(saisons), saisons[0], saisons[-1], len(plan), sum(etat.fait(n) for n in plan))

    # Neo4j : connexion ouverte à la première étape qui en a besoin, gardée ensuite.
    neo = {"driver": None, "base": None, "deja": None}

    def session():
        if neo["driver"] is None:
            import charger
            neo["driver"], neo["base"] = charger.connexion()
        return neo["driver"].session(database=neo["base"])

    def schema() -> dict:
        import charger
        with session() as s:
            edition = charger.verifier_version(s)
            charger.appliquer_schema(s, edition)
        return {"edition": edition}

    def connus() -> dict[str, set]:
        """Clés des référentiels de l'API, pour ne charger par saison que les nouveaux."""
        if neo["deja"] is None:
            d = tr.transformer([])
            neo["deja"] = {cat: {x["k"] for x in d[cat]}
                           for cat in ("saisons", "circuits", "pilotes", "constructeurs", "statuts")}
        return neo["deja"]

    def charger_referentiels() -> dict:
        import charger
        d = tr.transformer([])
        session().close()  # ouvre et vérifie la connexion
        charger.charger_referentiels(neo["driver"], neo["base"], d)
        return {"pilotes": len(d["pilotes"]), "ecuries": len(d["constructeurs"]),
                "circuits": len(d["circuits"])}

    def extraction(s: int):
        def f() -> dict:
            avant, refus = extracteur.requetes, extracteur.refus
            calendrier = extraire.extraire_saison(extracteur, s, forcer=s == saison_en_cours)
            return {"courses": len(calendrier), "requetes": extracteur.requetes - avant,
                    "refus_api": extracteur.refus - refus}
        return f

    def par_course(s: int, point: str):
        def f() -> dict:
            avant, refus = extracteur.requetes, extracteur.refus
            n = extraire.extraire_par_course(extracteur, s, point, forcer=s == saison_en_cours)
            return {"courses": n, "requetes": extracteur.requetes - avant,
                    "refus_api": extracteur.refus - refus}
        return f

    def chargement(s: int):
        def f() -> dict:
            import charger
            # Validation de la saison entière AVANT écriture : rien de partiel en base.
            d = tr.transformer([s])
            session().close()
            charger.charger_referentiels(neo["driver"], neo["base"], d, deja=connus())
            charger.charger_saison(neo["driver"], neo["base"], d)
            return {"courses": len(d["courses"]), "resultats": len(d["resultats"]),
                    "qualifications": len(d["qualifications"]), "sprints": len(d["sprints"]),
                    "arrets": len(d["arrets"]), "tours": len(d["tours"])}
        return f

    def controles() -> dict:
        import charger
        with session() as s:
            if not charger.controler(s):
                raise RuntimeError("au moins un invariant est violé (détail ci-dessus)")
        return {}

    def manifeste() -> dict:
        import manifeste as m
        if m.main() != 0:
            raise RuntimeError("anomalies dans le manifeste des sources (voir SOURCES.md)")
        return {}

    try:
        for nom in plan:
            if nom == "extraction:referentiels":
                continue  # déjà passée ci-dessus
            nature, _, suite = nom.partition(":")
            if nom == "chargement:schema":
                ex.etape(nom, schema)
            elif nom == "chargement:referentiels":
                ex.etape(nom, charger_referentiels, prerequis=("chargement:schema",))
            elif nature == "extraction":
                ex.etape(nom, extraction(int(suite)))
            elif nature == "arrets":
                ex.etape(nom, par_course(int(suite), "pitstops"), prerequis=(f"extraction:{suite}",))
            elif nature == "tours":
                ex.etape(nom, par_course(int(suite), "laps"), prerequis=(f"extraction:{suite}",))
            elif nature == "chargement":
                s = int(suite)
                requis = ["chargement:referentiels"]
                if not args.sans_extraction:
                    requis.append(f"extraction:{s}")
                    if args.arrets_depuis and s >= args.arrets_depuis:
                        requis.append(f"arrets:{s}")
                    if args.tours_depuis and s >= args.tours_depuis:
                        requis.append(f"tours:{s}")
                ex.etape(nom, chargement(s), prerequis=tuple(requis))
            elif nom == "controles":
                # Contrôles et manifeste sont refaits dès que cette exécution a changé quelque chose.
                if ex.bilan["faites"]:
                    etat.etapes.pop(nom, None)
                ex.etape(nom, controles, prerequis=("chargement:referentiels",))
            elif nom == "manifeste":
                if ex.bilan["faites"]:
                    etat.etapes.pop(nom, None)
                ex.etape(nom, manifeste)
    finally:
        if neo["driver"] is not None:
            neo["driver"].close()
    return ex


if __name__ == "__main__":
    sys.exit(main())

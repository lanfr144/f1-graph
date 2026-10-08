"""Applique le schéma et charge le cache dans Neo4j.

    python charger.py --schema            # contraintes et index seulement
    python charger.py                     # schéma + données (idempotent : MERGE)
    python charger.py --saisons 2023 2024 # un sous-ensemble des saisons en cache
    python charger.py --vider             # efface le graphe F1 (lui seul) avant de charger

Connexion lue dans .env (voir .env.example) : NEO4J_URI, NEO4J_USER,
NEO4J_PASSWORD, NEO4J_DATABASE.

Le chargement est idempotent : relancé, il met à jour sans dupliquer. Une
relation à valeur unique (course -> circuit, résultat -> statut…) dont la cible
a changé dans la source est remplacée, pas doublée. Il n'efface pas en revanche
un enregistrement disparu de la source : pour cela, --vider.

Après chargement, des contrôles d'invariants vérifient en base ce que Neo4j
Community ne sait pas imposer (cardinalité des relations) ; le script se
termine en erreur si l'un d'eux échoue.
"""
from __future__ import annotations

import argparse
import re
import sys

from commun import SCHEMA, exiger_env, lire_env
from transformer import DonneeInvalide, transformer

try:
    from neo4j import GraphDatabase
except ImportError:
    raise SystemExit("Module 'neo4j' absent : pip install -r requirements.txt (dans le .venv)")

LOT = 5000


# --- Schéma ------------------------------------------------------------------

def instructions(fichier) -> list[str]:
    texte = "\n".join(l for l in fichier.read_text(encoding="utf-8").splitlines()
                      if not l.lstrip().startswith("//"))
    return [i.strip() for i in texte.split(";") if i.strip()]


def verifier_version(session) -> str:
    composant = session.run("CALL dbms.components() YIELD name, versions, edition "
                            "WHERE name = 'Neo4j Kernel' RETURN versions[0] AS v, edition").single()
    if composant is None:
        raise SystemExit("dbms.components() ne renvoie pas 'Neo4j Kernel' : serveur non reconnu.")
    version, edition = composant["v"], composant["edition"]
    m = re.match(r"(\d+)\.(\d+)", version)
    if not m or (int(m[1]), int(m[2])) < (5, 7):
        raise SystemExit(f"Neo4j {version} : la version 5.7 au moins est requise "
                         "(contraintes d'unicité sur les relations).")
    print(f"Neo4j {version} ({edition})")
    return edition


def appliquer_schema(session, edition: str) -> None:
    fichiers = [SCHEMA / "01_contraintes.cypher", SCHEMA / "03_index.cypher"]
    if edition == "enterprise":
        fichiers.insert(1, SCHEMA / "02_contraintes_enterprise.cypher")
    else:
        print("  édition community : 02_contraintes_enterprise.cypher non applicable, "
              "les invariants seront contrôlés après chargement")
    for f in fichiers:
        liste = instructions(f)
        for i in liste:
            session.run(i).consume()
        print(f"  {f.name} : {len(liste)} instruction(s)")
    session.run("CALL db.awaitIndexes(600)").consume()


# --- Écriture ----------------------------------------------------------------

def executer(driver, base: str, requete: str, lignes: list[dict], quoi: str) -> None:
    """Exécute `requete` par lots ; exige que chaque ligne ait abouti."""
    traitees = 0
    with driver.session(database=base) as session:
        for debut in range(0, len(lignes), LOT):
            lot = lignes[debut:debut + LOT]
            n = session.execute_write(lambda tx: tx.run(requete, lignes=lot).single()["n"])
            if n != len(lot):
                raise SystemExit(f"{quoi} : {len(lot) - n} ligne(s) sur {len(lot)} sans extrémité "
                                 "trouvée en base (nœud absent). Chargement interrompu.")
            traitees += n
    print(f"  {quoi:42} {traitees:>8}")


def noeuds(driver, base, label: str, cle: str, lignes: list[dict], extra: str = "") -> None:
    requete = (f"UNWIND $lignes AS l MERGE (n:{label} {{{cle}: l.k}}) SET n += l.p {extra} "
               "RETURN count(*) AS n")
    executer(driver, base, requete, lignes, f"(:{label})")


def lien_unique(driver, base, a: str, ka: str, rel: str, b: str, kb: str,
                lignes: list[dict]) -> None:
    """(a)-[:rel]->(b), une seule cible par a : une ancienne cible différente est détachée."""
    requete = f"""
        UNWIND $lignes AS l
        MATCH (x:{a} {{{ka}: l.a}})
        MATCH (y:{b} {{{kb}: l.b}})
        OPTIONAL MATCH (x)-[ancien:{rel}]->(autre:{b}) WHERE autre <> y
        DELETE ancien
        WITH DISTINCT l, x, y
        MERGE (x)-[:{rel}]->(y)
        RETURN count(*) AS n"""
    executer(driver, base, requete, lignes, f"(:{a})-[:{rel}]->(:{b})")


def lien_cle(driver, base, a: str, ka: str, rel: str, b: str, kb: str,
             lignes: list[dict]) -> None:
    """(a)-[:rel {key}]->(b) avec propriétés : plusieurs liens par a, un par clé."""
    requete = f"""
        UNWIND $lignes AS l
        MATCH (x:{a} {{{ka}: l.a}})
        MATCH (y:{b} {{{kb}: l.b}})
        MERGE (x)-[r:{rel} {{key: l.key}}]->(y)
        SET r += l.p
        RETURN count(*) AS n"""
    executer(driver, base, requete, lignes, f"(:{a})-[:{rel}]->(:{b})")


def paires(lignes: list[dict], a: str, b: str) -> list[dict]:
    return [{"a": l[a], "b": l[b]} for l in lignes if l.get(b) is not None]


def charger(driver, base: str, d: dict[str, list[dict]]) -> None:
    # Nœuds de référence
    noeuds(driver, base, "Season", "year", d["saisons"])
    noeuds(driver, base, "Circuit", "circuitId", d["circuits"],
           extra="SET n.location = CASE WHEN l.lat IS NULL OR l.lng IS NULL THEN null "
                 "ELSE point({latitude: l.lat, longitude: l.lng}) END")
    noeuds(driver, base, "Driver", "driverId", d["pilotes"])
    noeuds(driver, base, "Constructor", "constructorId", d["constructeurs"])
    noeuds(driver, base, "Status", "name", d["statuts"])

    pays = sorted({c["country"] for c in d["circuits"] if c["country"]})
    noeuds(driver, base, "Country", "name", [{"k": p, "p": {}} for p in pays])
    nationalites = sorted({x["nationality"] for x in d["pilotes"] + d["constructeurs"] if x["nationality"]})
    noeuds(driver, base, "Nationality", "name", [{"k": n, "p": {}} for n in nationalites])

    lien_unique(driver, base, "Circuit", "circuitId", "LOCATED_IN", "Country", "name",
                [{"a": c["k"], "b": c["country"]} for c in d["circuits"] if c["country"]])
    lien_unique(driver, base, "Driver", "driverId", "HAS_NATIONALITY", "Nationality", "name",
                [{"a": x["k"], "b": x["nationality"]} for x in d["pilotes"] if x["nationality"]])
    lien_unique(driver, base, "Constructor", "constructorId", "HAS_NATIONALITY", "Nationality", "name",
                [{"a": x["k"], "b": x["nationality"]} for x in d["constructeurs"] if x["nationality"]])

    # Courses
    noeuds(driver, base, "Race", "raceId", d["courses"])
    lien_unique(driver, base, "Race", "raceId", "IN_SEASON", "Season", "year",
                [{"a": c["k"], "b": c["season"]} for c in d["courses"]])
    lien_unique(driver, base, "Race", "raceId", "HELD_AT", "Circuit", "circuitId",
                [{"a": c["k"], "b": c["circuitId"]} for c in d["courses"]])

    # Résultats : nœud n-aire relié à la course, au pilote, à l'écurie, au statut
    for label, cle in (("RaceResult", "resultats"), ("SprintResult", "sprints"),
                       ("QualifyingResult", "qualifications")):
        lignes = d[cle]
        if not lignes:
            continue
        noeuds(driver, base, label, "resultId", lignes)
        lien_unique(driver, base, label, "resultId", "IN_RACE", "Race", "raceId",
                    [{"a": l["k"], "b": l["raceId"]} for l in lignes])
        lien_unique(driver, base, label, "resultId", "OF_DRIVER", "Driver", "driverId",
                    [{"a": l["k"], "b": l["driverId"]} for l in lignes])
        lien_unique(driver, base, label, "resultId", "FOR_CONSTRUCTOR", "Constructor", "constructorId",
                    [{"a": l["k"], "b": l["constructorId"]} for l in lignes])
        if label != "QualifyingResult":
            lien_unique(driver, base, label, "resultId", "WITH_STATUS", "Status", "name",
                        [{"a": l["k"], "b": l["status"]} for l in lignes])

    for label, cle_label, cle in (("PitStop", "pitStopId", "arrets"), ("LapTime", "lapTimeId", "tours")):
        lignes = d[cle]
        if not lignes:
            print(f"  (:{label}) : rien en cache, non chargé")
            continue
        noeuds(driver, base, label, cle_label, lignes)
        lien_unique(driver, base, label, cle_label, "IN_RACE", "Race", "raceId",
                    [{"a": l["k"], "b": l["raceId"]} for l in lignes])
        lien_unique(driver, base, label, cle_label, "OF_DRIVER", "Driver", "driverId",
                    [{"a": l["k"], "b": l["driverId"]} for l in lignes])

    # Relations dérivées de la source (résultats et classements)
    lien_cle(driver, base, "Driver", "driverId", "DROVE_FOR", "Constructor", "constructorId",
             d["pilote_ecurie"])
    lien_cle(driver, base, "Driver", "driverId", "RANKED_IN", "Season", "year", d["classement_pilotes"])
    lien_cle(driver, base, "Constructor", "constructorId", "RANKED_IN", "Season", "year",
             d["classement_constructeurs"])


# --- Contrôles après chargement ----------------------------------------------

# Chaque requête renvoie le nombre de violations ; 0 est attendu.
INVARIANTS = {
    "course sans exactement une saison":
        "MATCH (r:Race) WHERE COUNT { (r)-[:IN_SEASON]->() } <> 1 RETURN count(r) AS n",
    "course sans exactement un circuit":
        "MATCH (r:Race) WHERE COUNT { (r)-[:HELD_AT]->() } <> 1 RETURN count(r) AS n",
    "course dont la saison diffère de son nœud Season":
        "MATCH (r:Race)-[:IN_SEASON]->(s:Season) WHERE r.season <> s.year RETURN count(r) AS n",
    "résultat sans exactement une course, un pilote, une écurie":
        "MATCH (x) WHERE (x:RaceResult OR x:SprintResult OR x:QualifyingResult) AND ("
        " COUNT { (x)-[:IN_RACE]->() } <> 1 OR COUNT { (x)-[:OF_DRIVER]->() } <> 1"
        " OR COUNT { (x)-[:FOR_CONSTRUCTOR]->() } <> 1) RETURN count(x) AS n",
    "résultat de course ou de sprint sans exactement un statut":
        "MATCH (x) WHERE (x:RaceResult OR x:SprintResult)"
        " AND COUNT { (x)-[:WITH_STATUS]->() } <> 1 RETURN count(x) AS n",
    "arrêt ou tour sans exactement une course et un pilote":
        "MATCH (x) WHERE (x:PitStop OR x:LapTime) AND ("
        " COUNT { (x)-[:IN_RACE]->() } <> 1 OR COUNT { (x)-[:OF_DRIVER]->() } <> 1)"
        " RETURN count(x) AS n",
    "DROVE_FOR dont la saison est absente":
        "MATCH ()-[r:DROVE_FOR]->() WHERE r.season IS NULL RETURN count(r) AS n",
    "RANKED_IN dont la saison ne correspond pas":
        "MATCH ()-[r:RANKED_IN]->(s:Season) WHERE r.season <> s.year RETURN count(r) AS n",
}


def controler(session) -> bool:
    ok = True
    print("Contrôles d'invariants :")
    for libelle, requete in INVARIANTS.items():
        n = session.run(requete).single()["n"]
        print(f"  {'OK ' if n == 0 else 'ÉCHEC'} {libelle}" + ("" if n == 0 else f" : {n}"))
        ok &= n == 0
    # Étiquettes et types connus du modèle : chaque comptage est servi par le
    # magasin de comptes de Neo4j, sans parcourir la base.
    print("Volumétrie :")
    for label in LABELS:
        n = session.run(f"MATCH (n:{label}) RETURN count(n) AS n").single()["n"]
        print(f"  (:{label}){'':{22 - len(label)}}{n:>10}")
    for rel in RELATIONS:
        n = session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS n").single()["n"]
        print(f"  [:{rel}]{'':{22 - len(rel)}}{n:>10}")
    return ok


LABELS = ("Season", "Circuit", "Country", "Nationality", "Driver", "Constructor", "Status", "Race",
          "RaceResult", "SprintResult", "QualifyingResult", "PitStop", "LapTime")
RELATIONS = ("LOCATED_IN", "HAS_NATIONALITY", "IN_SEASON", "HELD_AT", "IN_RACE", "OF_DRIVER",
             "FOR_CONSTRUCTOR", "WITH_STATUS", "DROVE_FOR", "RANKED_IN")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schema", action="store_true", help="appliquer le schéma seulement")
    p.add_argument("--saisons", type=int, nargs="+", help="saisons à charger (défaut : tout le cache)")
    p.add_argument("--vider", action="store_true",
                   help="effacer les nœuds du modèle F1 (et eux seuls) avant de charger")
    args = p.parse_args()

    lire_env()
    uri, base = exiger_env("NEO4J_URI"), exiger_env("NEO4J_DATABASE")
    auth = (exiger_env("NEO4J_USER"), exiger_env("NEO4J_PASSWORD"))

    donnees = None
    if not args.schema:
        # Transformer AVANT de toucher la base : une donnée invalide n'écrit rien.
        try:
            donnees = transformer(args.saisons)
        except DonneeInvalide as e:
            raise SystemExit(f"Données invalides, rien n'a été chargé : {e}") from None
        if not donnees["courses"]:
            raise SystemExit("Aucune course en cache : lancer d'abord extraire.py.")

    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()
        with driver.session(database=base) as session:
            edition = verifier_version(session)
            if args.vider:
                # Seules les étiquettes du modèle F1 : la base peut héberger d'autres graphes
                # (Neo4j Community n'offre qu'une base utilisateur).
                print("Effacement du graphe F1 :")
                for label in LABELS:
                    n = session.run(f"MATCH (n:{label}) RETURN count(n) AS n").single()["n"]
                    session.run(f"MATCH (n:{label}) CALL {{ WITH n DETACH DELETE n }} "
                                "IN TRANSACTIONS OF 10000 ROWS").consume()
                    print(f"  (:{label}) {n} nœud(s) effacé(s)")
            print("Schéma :")
            appliquer_schema(session, edition)
        if donnees is None:
            return 0
        print("Chargement :")
        charger(driver, base, donnees)
        with driver.session(database=base) as session:
            return 0 if controler(session) else 1


if __name__ == "__main__":
    sys.exit(main())

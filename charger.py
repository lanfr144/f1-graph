"""Applique le schéma et charge le cache dans Neo4j.

    python charger.py --schema            # contraintes et index seulement
    python charger.py                     # schéma + données (idempotent : MERGE)
    python charger.py --saisons 2023 2024 # un sous-ensemble des saisons en cache
    python charger.py --vider             # efface le graphe F1 (lui seul) avant de charger
    python charger.py --retirer           # retire le graphe F1 d'une base : nœuds, contraintes, index

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
import logging
import os
import re
import sys

from commun import SCHEMA, Verrou, exiger_env, journal_console, lire_env
from transformer import DonneeInvalide, transformer

try:
    from neo4j import GraphDatabase
except ImportError:
    raise SystemExit(f"Module 'neo4j' absent de l'interpréteur {sys.executable} : utiliser celui "
                     "du .venv (.venv/Scripts/python sous Windows), ou pip install -r requirements.txt")

LOT = 5000

log = logging.getLogger("f1.chargement")


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
    log.info("Neo4j %s (%s)", version, edition)
    return edition


def appliquer_schema(session, edition: str) -> None:
    fichiers = [SCHEMA / "00_migrations.cypher", SCHEMA / "01_contraintes.cypher", SCHEMA / "03_index.cypher"]
    if edition == "enterprise":
        fichiers.insert(2, SCHEMA / "02_contraintes_enterprise.cypher")
    else:
        log.info("  édition community : 02_contraintes_enterprise.cypher non applicable, "
                 "les invariants seront contrôlés après chargement")
    for f in fichiers:
        liste = instructions(f)
        for i in liste:
            session.run(i).consume()
        log.info("  %s : %d instruction(s)", f.name, len(liste))
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
    log.info("  %-42s %8d", quoi, traitees)


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
    charger_referentiels(driver, base, d)
    charger_saison(driver, base, d)


def charger_referentiels(driver, base: str, d: dict[str, list[dict]], deja: dict[str, set] | None = None) -> None:
    """Saisons, circuits, pilotes, écuries, statuts, pays, nationalités.

    `deja` (clés par catégorie) restreint l'écriture aux éléments encore inconnus :
    un chargement par saison n'ajoute ainsi que les pilotes ou écuries absents
    des listes de référence de l'API, sans réécrire les autres.
    """
    if deja:
        d = {**d, **{cat: [x for x in d[cat] if x["k"] not in deja.get(cat, set())]
                     for cat in ("saisons", "circuits", "pilotes", "constructeurs", "statuts")}}
    if not any(d[cat] for cat in ("saisons", "circuits", "pilotes", "constructeurs", "statuts")):
        return
    # Un seul nœud par code ISO 3166 alpha-3, porteur des deux étiquettes : il est à la
    # fois le pays d'un circuit et la nationalité d'un pilote ou d'une écurie.
    executer(driver, base, "UNWIND $lignes AS l MERGE (n:Country {iso3: l.k}) SET n:Nationality, n += l.p "
             "RETURN count(*) AS n", d["pays"], "(:Country:Nationality)")
    noeuds(driver, base, "Season", "year", d["saisons"])
    noeuds(driver, base, "Circuit", "circuitId", d["circuits"],
           extra="SET n.location = CASE WHEN l.lat IS NULL OR l.lng IS NULL THEN null "
                 "ELSE point({latitude: l.lat, longitude: l.lng}) END")
    noeuds(driver, base, "Driver", "driverId", d["pilotes"])
    noeuds(driver, base, "Constructor", "constructorId", d["constructeurs"])
    noeuds(driver, base, "Status", "name", d["statuts"])

    lien_unique(driver, base, "Circuit", "circuitId", "LOCATED_IN", "Country", "iso3",
                [{"a": c["k"], "b": c["country"]} for c in d["circuits"] if c["country"]])
    lien_unique(driver, base, "Driver", "driverId", "HAS_NATIONALITY", "Nationality", "iso3",
                [{"a": x["k"], "b": x["nationality"]} for x in d["pilotes"] if x["nationality"]])
    lien_unique(driver, base, "Constructor", "constructorId", "HAS_NATIONALITY", "Nationality", "iso3",
                [{"a": x["k"], "b": x["nationality"]} for x in d["constructeurs"] if x["nationality"]])


def charger_saison(driver, base: str, d: dict[str, list[dict]]) -> None:
    """Courses, résultats, arrêts, tours, écuries par saison, classements."""
    if not d["courses"]:
        return
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
            log.debug("  (:%s) : rien en cache pour ce périmètre", label)
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


# --- Relations dérivées ---------------------------------------------------------

# (Driver)-[:TEAMMATE_OF]->(Driver) : deux pilotes d'une même écurie la même saison.
# Dérivée de DROVE_FOR, reconstruite entièrement à chaque chargement (aucune paire
# périmée ne survit). Elle rend les recherches de chemins entre pilotes rapides :
# un plus court chemin sur une relation directe, au lieu d'un motif quantifié
# pilote-écurie-pilote filtré sur la saison, que Neo4j ne sait pas parcourir
# dans les deux sens à la fois.
COEQUIPIERS = """
    MATCH (a:Driver)-[p:DROVE_FOR]->(k:Constructor)<-[q:DROVE_FOR]-(b:Driver)
    WHERE p.season = q.season AND a.driverId < b.driverId
    WITH a, b, collect(DISTINCT p.season) AS saisons, collect(DISTINCT k.name) AS ecuries
    MERGE (a)-[t:TEAMMATE_OF {key: a.driverId + '|' + b.driverId}]->(b)
    SET t.seasons = saisons, t.constructors = ecuries,
        t.firstSeason = reduce(m = 9999, s IN saisons | CASE WHEN s < m THEN s ELSE m END),
        t.lastSeason = reduce(m = 0, s IN saisons | CASE WHEN s > m THEN s ELSE m END),
        t.seasonCount = size(saisons)
    RETURN count(*) AS n"""


def deriver(driver, base: str) -> dict:
    with driver.session(database=base) as session:
        session.run("MATCH ()-[t:TEAMMATE_OF]->() CALL (t) { DELETE t } IN TRANSACTIONS OF 10000 ROWS").consume()
        n = session.run(COEQUIPIERS).single()["n"]
    log.info("  %-42s %8d", "(:Driver)-[:TEAMMATE_OF]->(:Driver)", n)
    return {"coequipiers": n}


# --- Données complémentaires (complements.py) -----------------------------------

def charger_complements(driver, base: str, c: dict) -> dict:
    """Académies (Wikipédia) et suivis de la rédaction.

    Ces données ne sont pas datées par saison comme les résultats : elles sont
    remplacées en bloc à chaque chargement (une adhésion retirée de la source
    disparaît du graphe), sans toucher au reste du graphe.
    """
    executer(driver, base, "UNWIND $lignes AS l MERGE (a:Academy {academyId: l.k}) SET a += l.p "
             "RETURN count(*) AS n", c["academies"], "(:Academy)")
    executer(driver, base, """
        UNWIND $lignes AS l
        MATCH (a:Academy {academyId: l.a})
        MATCH (k:Constructor {constructorId: l.b})
        MERGE (a)-[:FEEDS]->(k)
        RETURN count(*) AS n""",
             [{"a": a["k"], "b": k} for a in c["academies"] for k in a["constructeurs"]],
             "(:Academy)-[:FEEDS]->(:Constructor)")
    cles = [x["key"] for x in c["adhesions"]]
    with driver.session(database=base) as s:
        s.run("MATCH ()-[m:MEMBER_OF]->() WHERE NOT m.key IN $cles DELETE m", cles=cles).consume()
    lien_cle(driver, base, "Driver", "driverId", "MEMBER_OF", "Academy", "academyId", c["adhesions"])

    with driver.session(database=base) as s:
        s.run("MERGE (r:Newsroom {name: 'rédaction'})").consume()
        s.run("MATCH (:Newsroom)-[f:FOLLOWS]->() DELETE f").consume()
    for nature, label, cle in (("driver", "Driver", "driverId"), ("constructor", "Constructor", "constructorId")):
        lignes = [x for x in c["suivis"] if x["nature"] == nature]
        if lignes:
            executer(driver, base, f"""
                UNWIND $lignes AS l
                MATCH (r:Newsroom {{name: 'rédaction'}})
                MATCH (x:{label} {{{cle}: l.k}})
                MERGE (r)-[f:FOLLOWS]->(x) SET f += l.p
                RETURN count(*) AS n""", lignes, f"(:Newsroom)-[:FOLLOWS]->(:{label})")
    if not c["suivis"]:
        log.info("  (:Newsroom)-[:FOLLOWS] : referentiel/suivis.csv ne liste aucun suivi")
    return {"academies": len(c["academies"]), "adhesions": len(c["adhesions"]), "suivis": len(c["suivis"])}


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
    "paire de coéquipiers sans TEAMMATE_OF":
        "MATCH (a:Driver)-[p:DROVE_FOR]->(:Constructor)<-[q:DROVE_FOR]-(b:Driver) "
        "WHERE p.season = q.season AND a.driverId < b.driverId AND NOT EXISTS { (a)-[:TEAMMATE_OF]->(b) } "
        "RETURN count(*) AS n",
    "pays ou nationalité sans code ISO, ou sans ses deux étiquettes":
        "MATCH (n) WHERE (n:Country OR n:Nationality) "
        "AND (n.iso3 IS NULL OR NOT (n:Country AND n:Nationality)) RETURN count(n) AS n",
    "RANKED_IN dont la saison ne correspond pas":
        "MATCH ()-[r:RANKED_IN]->(s:Season) WHERE r.season <> s.year RETURN count(r) AS n",
    "adhésion à une académie sans année de début, ou finissant avant de commencer":
        "MATCH ()-[m:MEMBER_OF]->() WHERE m.fromYear IS NULL "
        "OR (m.toYear IS NOT NULL AND m.toYear < m.fromYear) RETURN count(m) AS n",
    "académie qui n'alimente aucune écurie":
        "MATCH (a:Academy) WHERE NOT EXISTS { (a)-[:FEEDS]->(:Constructor) } RETURN count(a) AS n",
}


def controler(session) -> bool:
    ok = True
    log.info("Contrôles d'invariants :")
    for libelle, requete in INVARIANTS.items():
        n = session.run(requete).single()["n"]
        if n == 0:
            log.info("  OK    %s", libelle)
        else:
            log.error("  ÉCHEC %s : %d", libelle, n)
        ok &= n == 0
    # Étiquettes et types connus du modèle : chaque comptage est servi par le
    # magasin de comptes de Neo4j, sans parcourir la base.
    log.info("Volumétrie :")
    for label in LABELS:
        n = session.run(f"MATCH (n:{label}) RETURN count(n) AS n").single()["n"]
        log.info("  %-24s %10d", f"(:{label})", n)
    for rel in RELATIONS:
        n = session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS n").single()["n"]
        log.info("  %-24s %10d", f"[:{rel}]", n)
    return ok


LABELS = ("Season", "Circuit", "Country", "Nationality", "Driver", "Constructor", "Status", "Race",
          "RaceResult", "SprintResult", "QualifyingResult", "PitStop", "LapTime", "Academy", "Newsroom")
RELATIONS = ("LOCATED_IN", "HAS_NATIONALITY", "IN_SEASON", "HELD_AT", "IN_RACE", "OF_DRIVER",
             "FOR_CONSTRUCTOR", "WITH_STATUS", "DROVE_FOR", "RANKED_IN", "TEAMMATE_OF",
             "MEMBER_OF", "FEEDS", "FOLLOWS")


def connexion():
    """Pilote Neo4j et nom de base, lus dans .env ; la connexion est vérifiée."""
    lire_env()
    # Depuis l'hôte, la base de la pile Docker est joignable sur le port publié :
    # NEO4J_URI peut alors être omise, elle se déduit de NEO4J_BOLT_PORT_HOTE.
    if not os.environ.get("NEO4J_URI") and os.environ.get("NEO4J_BOLT_PORT_HOTE"):
        os.environ["NEO4J_URI"] = f"bolt://localhost:{os.environ['NEO4J_BOLT_PORT_HOTE']}"
        log.debug("NEO4J_URI déduite : %s", os.environ["NEO4J_URI"])
    uri, base = exiger_env("NEO4J_URI"), exiger_env("NEO4J_DATABASE")
    driver = GraphDatabase.driver(uri, auth=(exiger_env("NEO4J_USER"), exiger_env("NEO4J_PASSWORD")))
    try:
        driver.verify_connectivity()
    except Exception:
        driver.close()
        raise
    return driver, base


def vider(session) -> None:
    """Efface les nœuds du modèle F1, et eux seuls : la base peut héberger d'autres
    graphes (Neo4j Community n'offre qu'une base utilisateur)."""
    log.info("Effacement du graphe F1 :")
    for label in LABELS:
        n = session.run(f"MATCH (n:{label}) RETURN count(n) AS n").single()["n"]
        session.run(f"MATCH (n:{label}) CALL (n) {{ DETACH DELETE n }} "
                    "IN TRANSACTIONS OF 10000 ROWS").consume()
        log.info("  (:%s) %d nœud(s) effacé(s)", label, n)


def retirer(session) -> None:
    """Retire entièrement le graphe F1 d'une base qu'il partageait avec d'autres graphes :
    ses nœuds (et leurs relations), puis ses contraintes et index, reconnus à leur nom
    dans schema/. Rien d'autre n'est touché."""
    vider(session)
    contraintes, index = set(), set()
    for f in sorted(SCHEMA.glob("0[1-2]_*.cypher")):
        contraintes |= set(re.findall(r"CREATE CONSTRAINT (\w+)", f.read_text(encoding="utf-8")))
    index |= set(re.findall(r"CREATE (?:RANGE |POINT |FULLTEXT )INDEX (\w+)",
                            (SCHEMA / "03_index.cypher").read_text(encoding="utf-8")))
    presentes = {r["name"] for r in session.run("SHOW CONSTRAINTS YIELD name")}
    for nom in sorted(contraintes & presentes):
        session.run(f"DROP CONSTRAINT {nom} IF EXISTS").consume()
    presents = {r["name"] for r in session.run("SHOW INDEXES YIELD name")}
    for nom in sorted(index & presents):
        session.run(f"DROP INDEX {nom} IF EXISTS").consume()
    log.info("Retrait : %d contrainte(s) et %d index du modèle F1 supprimés",
             len(contraintes & presentes), len(index & presents))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schema", action="store_true", help="appliquer le schéma seulement")
    p.add_argument("--saisons", type=int, nargs="+", help="saisons à charger (défaut : tout le cache)")
    p.add_argument("--retirer", action="store_true",
                   help="retirer le graphe F1 de la base (nœuds, contraintes, index) et s'arrêter")
    p.add_argument("--vider", action="store_true",
                   help="effacer les nœuds du modèle F1 (et eux seuls) avant de charger")
    args = p.parse_args()
    journal_console()

    with Verrou():
        if args.retirer:
            driver, base = connexion()
            with driver, driver.session(database=base) as session:
                verifier_version(session)
                retirer(session)
            return 0
        donnees = None
        if not args.schema:
            # Transformer AVANT de toucher la base : une donnée invalide n'écrit rien.
            try:
                donnees = transformer(args.saisons)
            except DonneeInvalide as e:
                raise SystemExit(f"Données invalides, rien n'a été chargé : {e}") from None
            if not donnees["courses"]:
                raise SystemExit("Aucune course en cache : lancer d'abord extraire.py.")

        driver, base = connexion()
        with driver:
            with driver.session(database=base) as session:
                edition = verifier_version(session)
                if args.vider:
                    vider(session)
                log.info("Schéma :")
                appliquer_schema(session, edition)
            if donnees is None:
                return 0
            log.info("Chargement :")
            charger(driver, base, donnees)
            deriver(driver, base)
            with driver.session(database=base) as session:
                return 0 if controler(session) else 1


if __name__ == "__main__":
    sys.exit(main())

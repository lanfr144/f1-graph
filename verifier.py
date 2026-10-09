"""Vérifie l'état de la base Neo4j et la complétude des chargements.

    python verifier.py               # schéma, invariants, rapprochement cache <-> base
    python verifier.py --saisons 2024 2025

Quatre volets, chacun en lecture seule :
  1. schéma : chaque contrainte et chaque index attendus existent et sont ONLINE ;
  2. invariants : les contrôles de charger.py (cardinalité des relations…) ;
  3. rapprochement : pour chaque saison, ce que le cache contient (après
     transformation) comparé, nombre par nombre, à ce que la base contient ;
  4. cohérence métier : un vainqueur par course disputée, un champion par saison
     close, aucun résultat sans points, etc.

Le rapprochement classe chaque saison : « complète », « partielle » (écarts listés),
« absente de la base » ou « absente du cache ». Code de sortie 1 au moindre écart.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import Counter

from commun import SCHEMA, journal_console
from transformer import DonneeInvalide, saisons_en_cache, transformer

log = logging.getLogger("f1.verification")

# Nombre en base, par saison, de chaque catégorie produite par transformer.py.
COMPTAGES = {
    "courses": "MATCH (r:Race) WHERE r.season = $s RETURN count(r) AS n",
    "resultats": "MATCH (:Race {season: $s})<-[:IN_RACE]-(x:RaceResult) RETURN count(x) AS n",
    "sprints": "MATCH (:Race {season: $s})<-[:IN_RACE]-(x:SprintResult) RETURN count(x) AS n",
    "qualifications": "MATCH (:Race {season: $s})<-[:IN_RACE]-(x:QualifyingResult) RETURN count(x) AS n",
    "arrets": "MATCH (:Race {season: $s})<-[:IN_RACE]-(x:PitStop) RETURN count(x) AS n",
    "tours": "MATCH (:Race {season: $s})<-[:IN_RACE]-(x:LapTime) RETURN count(x) AS n",
    "pilote_ecurie": "MATCH ()-[r:DROVE_FOR]->() WHERE r.season = $s RETURN count(r) AS n",
    "classement_pilotes": "MATCH (:Driver)-[r:RANKED_IN]->(:Season {year: $s}) RETURN count(r) AS n",
    "classement_constructeurs": "MATCH (:Constructor)-[r:RANKED_IN]->(:Season {year: $s}) RETURN count(r) AS n",
}


def noms_attendus(fichier: str, motif: str) -> set[str]:
    texte = (SCHEMA / fichier).read_text(encoding="utf-8")
    return set(re.findall(motif, texte))


def verifier_schema(session, edition: str) -> int:
    log.info("1. Schéma")
    ecarts = 0
    attendues = noms_attendus("01_contraintes.cypher", r"CREATE CONSTRAINT (\w+)")
    if edition == "enterprise":
        attendues |= noms_attendus("02_contraintes_enterprise.cypher", r"CREATE CONSTRAINT (\w+)")
    presentes = {r["name"] for r in session.run("SHOW CONSTRAINTS YIELD name")}
    for nom in sorted(attendues - presentes):
        log.error("  contrainte absente : %s", nom)
        ecarts += 1
    log.info("  contraintes : %d attendue(s), %d présente(s)%s", len(attendues),
             len(attendues & presentes), "" if edition == "enterprise" else
             " (édition community : contraintes d'existence et de type non applicables)")

    index_attendus = noms_attendus("03_index.cypher", r"CREATE (?:RANGE |POINT |FULLTEXT )INDEX (\w+)")
    etats = {r["name"]: (r["state"], r["populationPercent"])
             for r in session.run("SHOW INDEXES YIELD name, state, populationPercent")}
    for nom in sorted(index_attendus):
        if nom not in etats:
            log.error("  index absent : %s", nom)
            ecarts += 1
        elif etats[nom][0] != "ONLINE":
            log.error("  index %s : état %s (%s %%)", nom, *etats[nom])
            ecarts += 1
    hors_ligne = [n for n, (e, _) in etats.items() if e != "ONLINE"]
    for nom in hors_ligne:
        if nom not in index_attendus:
            log.warning("  index %s (hors modèle F1) : état %s", nom, etats[nom][0])
    log.info("  index du modèle : %d attendu(s), %d ONLINE", len(index_attendus),
             sum(1 for n in index_attendus if etats.get(n, ("",))[0] == "ONLINE"))
    return ecarts


def rapprocher(session, saisons: list[int]) -> tuple[int, Counter]:
    log.info("3. Rapprochement cache <-> base, saison par saison")
    en_base = {r["s"] for r in session.run("MATCH (r:Race) RETURN DISTINCT r.season AS s")}
    en_cache = set(saisons_en_cache())
    ecarts = 0
    bilan: Counter = Counter()
    for s in sorted(set(saisons) | (en_base & set(saisons))):
        if s not in en_cache:
            log.warning("  %d : absente du cache (présente en base : %s)", s, "oui" if s in en_base else "non")
            bilan["absente du cache"] += 1
            continue
        try:
            attendu = transformer([s])
        except DonneeInvalide as e:
            log.error("  %d : cache invalide — %s", s, e)
            bilan["cache invalide"] += 1
            ecarts += 1
            continue
        mesure = {cat: session.run(q, s=s).single()["n"] for cat, q in COMPTAGES.items()}
        if s not in en_base:
            log.warning("  %d : en cache (%d courses, %d résultats) mais ABSENTE de la base",
                        s, len(attendu["courses"]), len(attendu["resultats"]))
            bilan["absente de la base"] += 1
            ecarts += 1
            continue
        differences = {cat: (len(attendu[cat]), mesure[cat]) for cat in COMPTAGES
                       if len(attendu[cat]) != mesure[cat]}
        if differences:
            detail = ", ".join(f"{c} cache {a} / base {b}" for c, (a, b) in differences.items())
            log.error("  %d : PARTIELLE — %s", s, detail)
            bilan["partielle"] += 1
            ecarts += 1
        else:
            resume = ", ".join(f"{c} {mesure[c]}" for c in ("courses", "resultats", "qualifications",
                                                              "sprints", "arrets", "tours") if mesure[c])
            log.info("  %d : complète — %s", s, resume)
            bilan["complète"] += 1
    return ecarts, bilan


# Chaque requête renvoie des lignes fautives ; aucune n'est attendue.
COHERENCE = {
    "course disputée (résultats chargés) sans vainqueur unique":
        """MATCH (r:Race) WHERE EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
           WITH r, COUNT { (r)<-[:IN_RACE]-(x:RaceResult WHERE x.position = 1) } AS v
           WHERE v = 0 RETURN r.raceId AS cle, v AS valeur""",
    "saison close classée sans champion pilote unique":
        """MATCH (s:Season) WHERE EXISTS { (s)<-[:RANKED_IN]-(:Driver) } AND s.year < date().year
           WITH s, COUNT { (s)<-[k:RANKED_IN]-(:Driver) WHERE k.position = 1 } AS c
           WHERE c <> 1 RETURN s.year AS cle, c AS valeur""",
    "résultat dont la course n'appartient pas à la saison de son identifiant":
        """MATCH (x:RaceResult)-[:IN_RACE]->(r:Race)
           WHERE NOT x.resultId STARTS WITH r.raceId + '-'
           RETURN x.resultId AS cle, r.raceId AS valeur LIMIT 20""",
    "points négatifs":
        """MATCH (x:RaceResult) WHERE x.points < 0 RETURN x.resultId AS cle, x.points AS valeur LIMIT 20""",
    "classement pilote : victoires supérieures aux victoires chargées":
        """MATCH (d:Driver)-[k:RANKED_IN]->(s:Season)
           WITH d, k, s, COUNT { (d)<-[:OF_DRIVER]-(x:RaceResult WHERE x.position = 1)-[:IN_RACE]->(:Race {season: s.year}) } AS v
           WHERE EXISTS { (s)<-[:IN_SEASON]-(:Race)<-[:IN_RACE]-(:RaceResult) } AND k.wins > v
           RETURN d.driverId + ' ' + toString(s.year) AS cle, toString(k.wins) + ' > ' + toString(v) AS valeur LIMIT 20""",
    "course sans date":
        "MATCH (r:Race) WHERE r.date IS NULL RETURN r.raceId AS cle, null AS valeur LIMIT 20",
}


def verifier_coherence(session) -> int:
    log.info("4. Cohérence métier")
    ecarts = 0
    for libelle, requete in COHERENCE.items():
        lignes = list(session.run(requete))
        if lignes:
            ecarts += 1
            exemples = ", ".join(f"{l['cle']} ({l['valeur']})" for l in lignes[:5])
            log.error("  ÉCHEC %s : %d cas, ex. %s", libelle, len(lignes), exemples)
        else:
            log.info("  OK    %s", libelle)
    return ecarts


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--saisons", type=int, nargs="+",
                   help="saisons à rapprocher (défaut : toutes celles du cache et de la base)")
    args = p.parse_args()
    journal_console()

    import charger
    driver, base = charger.connexion()
    with driver, driver.session(database=base) as session:
        edition = charger.verifier_version(session)
        ecarts = verifier_schema(session, edition)

        log.info("2. Invariants")
        if not charger.controler(session):
            ecarts += 1

        saisons = args.saisons
        if saisons is None:
            en_base = {r["s"] for r in session.run("MATCH (r:Race) RETURN DISTINCT r.season AS s")}
            saisons = sorted(set(saisons_en_cache()) | en_base)
        e, bilan = rapprocher(session, saisons)
        ecarts += e
        ecarts += verifier_coherence(session)

    log.info("BILAN : %s ; %d écart(s).", ", ".join(f"{n} saison(s) {k}" for k, n in sorted(bilan.items())),
             ecarts)
    return 0 if ecarts == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

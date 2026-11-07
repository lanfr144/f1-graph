"""Plans d'exécution de toutes les requêtes des questions : coût mesuré, parcours sans index.

    python plans.py                 # PROFILE de chaque prérequête et requête, tableau de synthèse
    python plans.py 2 16            # certaines questions
    python plans.py 2 --detail      # + l'arbre des opérateurs
    python plans.py --doc           # écrit docs/plans-execution.md

PROFILE exécute réellement la requête (toutes sont en lecture seule) et compte les accès
à la base (« db hits ») de chaque opérateur ; EXPLAIN ne fait qu'annoncer le plan.

Signalé à titre d'alerte, car c'est ce qu'un index peut éviter :
  AllNodesScan, NodeByLabelScan, relation parcourue par type (…RelationshipTypeScan,
  …AllRelationshipsScan), lorsqu'un Filter sur une propriété les suit.
Un parcours n'est pas une faute en soi : sur 77 saisons, lire tout est le bon plan.
Un index ne se pose que si la mesure avant/après montre un gain.
"""
from __future__ import annotations

import argparse
import logging
import sys

from commun import RACINE, journal_console

SCANS = ("AllNodesScan", "NodeByLabelScan", "RelationshipTypeScan", "AllRelationshipsScan")


def _op(p: dict) -> dict:
    a = p.get("args") or p.get("arguments") or {}
    return {"nom": p.get("operatorType", "?").split("@")[0], "details": str(a.get("Details", "")),
            "hits": int(p.get("dbHits", a.get("DbHits", 0)) or 0), "lignes": int(p.get("rows", a.get("Rows", 0)) or 0),
            "enfants": p.get("children", [])}


def aplatir(plan: dict, profondeur: int = 0) -> list[dict]:
    o = _op(plan)
    o["profondeur"] = profondeur
    sortie = [o]
    for e in o["enfants"]:
        sortie += aplatir(e, profondeur + 1)
    return sortie


def profiler(session, cypher: str, params: dict) -> dict:
    resultat = session.run("PROFILE " + cypher, params)
    lignes = sum(1 for _ in resultat)
    resume = resultat.consume()
    ops = aplatir(resume.profile)
    return {"ops": ops, "lignes": lignes, "hits": sum(o["hits"] for o in ops),
            "ms": (resume.result_available_after or 0) + (resume.result_consumed_after or 0),
            "scans": [o for o in ops if any(s in o["nom"] for s in SCANS)],
            "index": sorted({o["nom"] for o in ops if "Index" in o["nom"]})}


def mesurer(session, questions: dict, choisies: list[int]) -> list[dict]:
    import questions as qmod
    mesures = []
    for n in choisies:
        q = questions[n]
        if not q["requete"]:
            continue
        r = qmod.executer_question(session, q)
        for pre in q["prerequetes"]:
            mesures.append({"q": n, "genre": "prérequête", **profiler(session, pre["cypher"], r["params"])})
        mesures.append({"q": n, "genre": "requête", **profiler(session, q["requete"], r["params"])})
    return mesures


def n(x: int) -> str:
    return f"{x:,}".replace(",", " ")


ENTETE = """# Plans d'exécution et index

> Tableau de mesure généré par `python plans.py --doc` — ne pas modifier à la main.

## Comment lire ce document

Avant d'exécuter une requête, Neo4j choisit un **plan** : l'ordre dans lequel il parcourt
le graphe. Deux commandes le montrent :

- `EXPLAIN` annonce le plan, sans exécuter la requête ;
- `PROFILE` exécute la requête et compte, pour chaque opérateur, ses **accès à la base**
  (*db hits*). C'est la vraie mesure du travail : plus il y en a, plus c'est lent.

Un **index** est comme l'index d'un livre : il évite de tout lire pour trouver une valeur.
Il ne sert donc que si le coût vient d'un parcours qui lit beaucoup pour garder peu. Il
ralentit aussi chaque écriture : on n'en pose que si la mesure montre un gain.

Pour voir ces plans : page « Questions » de l'interface, volet « Comprendre la requête » ;
ou `python plans.py 2 --detail`.

## Optimisations du 7 novembre 2026

Mesures avant/après sur la même base ; réponses comparées ligne à ligne, identiques.

| Requête | Avant (db hits) | Après (db hits) | Cause et remède |
|---|---:|---:|---|
| Q2, face-à-face | 102 634 435 | 170 464 | Motif : pour chaque paire, toute la carrière du second pilote était relue (30,8 millions de lignes). **Un index n'y pouvait rien** ; requête réécrite pour lire chaque carrière une fois, puis travailler course par course. De 40 s à moins d'une seconde. |
| Q7, duels contre les favoris | 15 211 038 | 500 907 | Même cause, même remède. |
| Q3, anciennes écuries | 49 386 | 40 906 | Index `drove_for_season` : la grille de la saison sans lire les 3 471 engagements. |
| Q9, transferts | 30 027 | 21 547 | Index `drove_for_season`. |
| Q11, prérequête | 9 156 | 676 | Index `drove_for_season`. |

## Ce qui n'appelle pas d'index

- Les parcours `NodeByLabelScan` restants lisent les 7 académies ou les 1 172 courses :
  lire tout est alors le bon plan (au plus 42 000 accès, quelques dizaines de ms).
- Q16 signale un « produit cartésien » : deux recherches par clé unique, une ligne chacune.
  L'avertissement de Neo4j est sans conséquence ici.

## Mesures actuelles

"""


def usage_index(session) -> list[str]:
    """Lectures de chaque index depuis le démarrage de Neo4j : un index jamais lu est à questionner."""
    lignes = ["| Index | Type | Lectures depuis le démarrage de Neo4j |", "|---|---|---:|"]
    for r in session.run("SHOW INDEXES YIELD name, type, readCount WHERE type <> 'LOOKUP' "
                         "AND NOT name ENDS WITH '_unique' RETURN name, type, readCount ORDER BY readCount DESC"):
        lignes.append(f"| `{r['name']}` | {r['type']} | {n(r['readCount'] or 0)} |")
    return lignes


def tableau(mesures: list[dict]) -> list[str]:
    lignes = ["| Question | Requête | Lignes | Accès base (db hits) | Durée (ms) | Index utilisés | Parcours sans index |",
              "|---|---|---:|---:|---:|---|---|"]
    for m in mesures:
        scans = ", ".join(f"{o['nom']} ({o['lignes']})" for o in m["scans"]) or "—"
        lignes.append(f"| Q{m['q']} | {m['genre']} | {m['lignes']} | {n(m['hits'])} | {n(m['ms'])} | "
                      f"{', '.join(m['index']) or '—'} | {scans} |")
    return lignes


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("numeros", type=int, nargs="*")
    p.add_argument("--detail", action="store_true", help="afficher l'arbre des opérateurs")
    p.add_argument("--doc", action="store_true", help="écrire docs/plans-execution.md")
    args = p.parse_args()
    journal_console()
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    import charger
    import questions as qmod
    questions = qmod.lire_questions()
    choisies = args.numeros or sorted(questions)
    driver, base = charger.connexion()
    with driver, driver.session(database=base) as session:
        mesures = mesurer(session, questions, choisies)
        usage = usage_index(session)

    lignes = tableau(mesures)
    print("\n".join(lignes))
    print(f"\nTotal : {n(sum(m['hits'] for m in mesures))} db hits, {n(sum(m['ms'] for m in mesures))} ms")
    print("\n".join(["", *usage]))
    if args.detail:
        for m in mesures:
            print(f"\nQ{m['q']} {m['genre']}")
            for o in m["ops"]:
                print(f"{'  ' * o['profondeur']}{o['nom']} [{o['lignes']} lignes, {o['hits']} hits] {o['details'][:110]}")
    if args.doc:
        total = f"Total : {n(sum(m['hits'] for m in mesures))} accès à la base."
        corps = [ENTETE + "\n".join(lignes), "", total, "", "## Usage des index", "",
                 "Les index peu lus servent les requêtes de référence de `schema/04_requetes.cypher` "
                 "(recherche par nom, distance, palmarès), pas les seize questions.", "", *usage]
        (RACINE / "docs" / "plans-execution.md").write_text("\n".join(corps) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

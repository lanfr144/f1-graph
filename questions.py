"""Exécute les questions de requetes/questions.cypher, en affichant chaque requête.

    python questions.py                     # toutes les questions
    python questions.py 1 16                # certaines
    python questions.py 16 --param a="'alonso'" --param b="'hamilton'"
    python questions.py --liste             # numéros, titres et couverture
    python questions.py 1 --sans-cypher     # réponses seules

Pour chaque question : les paramètres fixes (@param), puis chaque prérequête —
son texte, puis les valeurs qu'elle a trouvées dans la base —, puis la requête
finale avec ses paramètres, puis la réponse. Une valeur de --param est une
expression Cypher ('alonso' entre apostrophes, date('2026-10-12')) ; elle
l'emporte sur la valeur fixe comme sur celle d'une prérequête.
"""
from __future__ import annotations

import argparse
import re
import sys
import textwrap

from commun import RACINE

FICHIER = RACINE / "requetes" / "questions.cypher"


def lire_questions() -> dict[int, dict]:
    """Découpe le fichier en blocs « // === Qn | titre », puis en prérequêtes et requête."""
    questions = {}
    texte = FICHIER.read_text(encoding="utf-8").replace("\r\n", "\n")
    for bloc in re.split(r"^// === Q", texte, flags=re.M)[1:]:
        entete, _, reste = bloc.partition("\n")
        numero, _, titre = entete.partition("|")
        params, notes, sections, etapes = {}, [], [], []
        courante = None  # None : commentaires d'en-tête du bloc
        for ligne in reste.splitlines():
            m = re.match(r"// --- (prérequête|requête)\b\s*:?\s*(.*)", ligne)
            if m:
                courante = {"genre": m[1], "but": m[2].strip(), "lignes": []}
                sections.append(courante)
            elif courante is None:
                p = re.match(r"// @param (\w+) = (.+)", ligne)
                e = re.match(r"// @etape (.+)", ligne)
                if p:
                    params[p[1]] = p[2].strip()
                elif e:
                    # « titre | motif parcouru | filtres appliqués »
                    champs = [c.strip() for c in e[1].split(" | ")] + ["", ""]
                    etapes.append({"titre": champs[0], "motif": champs[1], "filtres": champs[2]})
                elif ligne.startswith("//"):
                    notes.append(ligne[2:].strip())
                elif ligne.strip():
                    # Requête sans marqueur : tout le reste du bloc.
                    courante = {"genre": "requête", "but": "", "lignes": [ligne]}
                    sections.append(courante)
            elif ligne.startswith("//") and not courante["lignes"]:
                courante["but"] += " " + ligne[2:].strip()  # suite du libellé
            elif ligne.strip() and not ligne.lstrip().startswith("//"):
                courante["lignes"].append(ligne)
        for sec in sections:
            sec["cypher"] = "\n".join(sec.pop("lignes")).strip().rstrip(";").strip()
        questions[int(numero)] = {
            "titre": titre.strip(), "notes": notes, "params": params, "etapes": etapes,
            "prerequetes": [s for s in sections if s["genre"] == "prérequête" and s["cypher"]],
            "requete": next((s["cypher"] for s in sections if s["genre"] == "requête" and s["cypher"]), ""),
        }
    return questions


def executer_question(session, q: dict, surcharges: dict[str, str] | None = None) -> dict:
    """Paramètres fixes, prérequêtes, puis requête. Utilisée par la ligne de commande et le web.

    `surcharges` : nom -> expression Cypher ; elle l'emporte sur la valeur fixe comme
    sur celle d'une prérequête. Renvoie tout ce qui a été exécuté, pour l'afficher.
    """
    surcharges = surcharges or {}

    def evaluer(expression: str):
        return session.run(f"RETURN {expression} AS v").single()["v"]

    params = {k: evaluer(surcharges.get(k, v)) for k, v in q["params"].items()}
    executees = []
    for pre in q["prerequetes"]:
        ligne = session.run(pre["cypher"], params).single()
        if ligne is None:
            raise RuntimeError(f"la prérequête « {pre['but']} » ne renvoie aucune ligne : la base est-elle chargée ?")
        trouvees = dict(ligne)
        executees.append({**pre, "valeurs": trouvees,
                          "remplacees": sorted(k for k in trouvees if k in surcharges)})
        for nom, valeur in trouvees.items():
            params[nom] = evaluer(surcharges[nom]) if nom in surcharges else valeur
    resultat = session.run(q["requete"], params)
    lignes = [dict(r) for r in resultat]
    return {"prerequetes": executees, "params": params, "cypher": q["requete"],
            "colonnes": list(resultat.keys()), "lignes": lignes}


def montrer_cypher(cypher: str) -> None:
    print(textwrap.indent(cypher, "      │ "))


# --- Explications : les étapes « @etape » rendues en texte, Graphviz et Mermaid --------

def explication_texte(q: dict) -> str:
    return "\n".join(f"  {i}. {e['titre']} — parcourt {e['motif']}\n       filtres : {e['filtres'] or 'aucun'}"
                     for i, e in enumerate(q["etapes"], 1))


def explication_dot(q: dict) -> str:
    """Schéma Graphviz : une boîte par étape (titre, motif parcouru, filtres)."""
    def echapper(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    lignes = ['digraph etapes {', '  rankdir=TB; nodesep=0.3; ranksep=0.35;',
              '  node [shape=plain, fontname="Helvetica", fontsize=11];', '  edge [color="#888780"];']
    for i, e in enumerate(q["etapes"], 1):
        filtres = "<BR/>".join(echapper(f.strip()) for f in e["filtres"].split(" ; ") if f.strip()) or "aucun filtre"
        lignes.append(
            f'  e{i} [label=<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="5" COLOR="#378ADD">'
            f'<TR><TD ALIGN="LEFT" BGCOLOR="#E6F1FB"><B>{i}. {echapper(e["titre"])}</B></TD></TR>'
            f'<TR><TD ALIGN="LEFT"><FONT FACE="Courier" POINT-SIZE="10">{echapper(e["motif"])}</FONT></TD></TR>'
            f'<TR><TD ALIGN="LEFT"><FONT COLOR="#993C1D">{filtres}</FONT></TD></TR></TABLE>>];')
        if i > 1:
            lignes.append(f"  e{i - 1} -> e{i};")
    lignes.append("}")
    return "\n".join(lignes)


def explication_mermaid(q: dict) -> str:
    def echapper(t: str) -> str:
        return t.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;").replace("|", "#124;")

    lignes = ["flowchart TD"]
    for i, e in enumerate(q["etapes"], 1):
        lignes.append(f'  E{i}["<b>{i}. {echapper(e["titre"])}</b><br/>{echapper(e["motif"])}'
                      f'<br/><i>{echapper(e["filtres"] or "aucun filtre")}</i>"]')
        if i > 1:
            lignes.append(f"  E{i - 1} --> E{i}")
    return "\n".join(lignes)


def generer_doc(questions: dict) -> str:
    """docs/explication-requetes.md : pour chaque question, ses étapes et leurs filtres."""
    sortie = ["# Explication des requêtes", "",
              "> Généré par `python questions.py --doc` à partir des lignes `@etape` de",
              "> `requetes/questions.cypher` — ne pas modifier à la main.", "",
              "Chaque question est décomposée en étapes : ce que l'étape **parcourt** dans le graphe,",
              "puis les **filtres** appliqués (`WHERE`, `LIMIT`, comparaisons). L'interface web",
              "(page « Questions ») montre en plus le **plan d'exécution** réel de Neo4j.", ""]
    for n in sorted(questions):
        q = questions[n]
        sortie += [f"## Q{n} — {q['titre']}", "", " ".join(q["notes"]), ""]
        if not q["etapes"]:
            continue
        sortie += ["| Étape | Parcourt | Filtres |", "|---|---|---|"]
        sortie += [f"| {i}. {e['titre']} | `{e['motif'].replace('|', '¦')}` | {e['filtres'].replace('|', '¦') or '—'} |"
                   for i, e in enumerate(q["etapes"], 1)]
        sortie += ["", "```mermaid", explication_mermaid(q), "```", ""]
    return "\n".join(sortie) + "\n"


def afficher(lignes: list[dict], maximum: int) -> None:
    if not lignes:
        print("    → aucune ligne")
        return
    for ligne in lignes[:maximum]:
        print("    → " + " | ".join(f"{k}={v}" for k, v in ligne.items()))
    if len(lignes) > maximum:
        print(f"    … {len(lignes) - maximum} ligne(s) de plus")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("numeros", type=int, nargs="*", help="questions à exécuter (défaut : toutes)")
    p.add_argument("--param", action="append", default=[], metavar="NOM=EXPRESSION",
                   help="surcharge d'un paramètre, expression Cypher")
    p.add_argument("--lignes", type=int, default=10, help="lignes affichées par question (défaut 10)")
    p.add_argument("--liste", action="store_true", help="lister les questions sans les exécuter")
    p.add_argument("--sans-cypher", action="store_true", help="ne pas afficher le texte des requêtes")
    p.add_argument("--explications", action="store_true",
                   help="afficher les étapes et filtres de chaque question, sans exécuter")
    p.add_argument("--doc", action="store_true", help="écrire docs/explication-requetes.md et s'arrêter")
    args = p.parse_args()

    questions = lire_questions()
    if args.doc:
        cible = RACINE / "docs" / "explication-requetes.md"
        cible.write_text(generer_doc(questions), encoding="utf-8", newline="\n")
        print(f"{cible} écrit ({sum(len(q['etapes']) for q in questions.values())} étapes)")
        return 0
    choisies = args.numeros or sorted(questions)
    inconnues = [n for n in choisies if n not in questions]
    if inconnues:
        raise SystemExit(f"Question(s) inconnue(s) : {inconnues} ; disponibles : {sorted(questions)}")
    surcharges = dict(s.split("=", 1) for s in args.param)

    if args.liste or args.explications:
        for n in choisies:
            q = questions[n]
            print(f"Q{n:<2} {q['notes'][0] if q['notes'] else ''}\n    {q['titre']}")
            if args.explications and q["etapes"]:
                print(explication_texte(q))
        return 0

    import charger
    driver, base = charger.connexion()
    erreurs = 0
    with driver, driver.session(database=base) as session:
        for n in choisies:
            q = questions[n]
            print(f"\n{'═' * 100}\nQ{n} — {q['titre']}")
            for note in q["notes"][:3]:
                print(f"    {note}")
            if not q["requete"]:
                continue
            try:
                r = executer_question(session, q, surcharges)
            except Exception as e:  # une question en échec n'empêche pas les suivantes
                print(f"    ÉCHEC : {e}")
                erreurs += 1
                continue
            for pre in r["prerequetes"]:
                print(f"\n  Prérequête — {pre['but']}")
                if not args.sans_cypher:
                    montrer_cypher(pre["cypher"])
                print("    valeurs trouvées : " + ", ".join(
                    f"{k}={v}" + (" (remplacée par --param)" if k in pre["remplacees"] else "")
                    for k, v in pre["valeurs"].items()))
            print("\n  Requête" + (" — paramètres : " + ", ".join(f"${k}={v}" for k, v in r["params"].items())
                                   if r["params"] else ""))
            if not args.sans_cypher:
                montrer_cypher(r["cypher"])
            print("\n  Réponse :")
            afficher(r["lignes"], args.lignes)
    return 1 if erreurs else 0


if __name__ == "__main__":
    sys.exit(main())

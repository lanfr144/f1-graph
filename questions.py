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
        params, notes, sections = {}, [], []
        courante = None  # None : commentaires d'en-tête du bloc
        for ligne in reste.splitlines():
            m = re.match(r"// --- (prérequête|requête)\b\s*:?\s*(.*)", ligne)
            if m:
                courante = {"genre": m[1], "but": m[2].strip(), "lignes": []}
                sections.append(courante)
            elif courante is None:
                p = re.match(r"// @param (\w+) = (.+)", ligne)
                if p:
                    params[p[1]] = p[2].strip()
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
            "titre": titre.strip(), "notes": notes, "params": params,
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
    args = p.parse_args()

    questions = lire_questions()
    choisies = args.numeros or sorted(questions)
    inconnues = [n for n in choisies if n not in questions]
    if inconnues:
        raise SystemExit(f"Question(s) inconnue(s) : {inconnues} ; disponibles : {sorted(questions)}")
    surcharges = dict(s.split("=", 1) for s in args.param)

    if args.liste:
        for n in choisies:
            q = questions[n]
            print(f"Q{n:<2} {q['notes'][0] if q['notes'] else ''}\n    {q['titre']}")
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

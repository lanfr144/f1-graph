"""Génère SOURCES.md (versionné) à partir du cache local donnees/brut/.

Les données elles-mêmes ne sont jamais versionnées : elles sont sous licence
CC BY-NC-SA 4.0 et se reconstituent par `python extraire.py`. Ce manifeste dit
d'où elles viennent, sous quelle licence, et quelle empreinte chaque réponse
avait au moment de l'extraction.

La licence n'est pas recopiée de mémoire : elle est relue dans les conditions
d'utilisation publiées par l'éditeur. Si elles sont injoignables ou si leur
formulation a changé, le manifeste le signale au lieu de supposer.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
import urllib.request
from collections import defaultdict

from commun import CACHE, DONNEES, RACINE, USER_AGENT

# Le SOURCES.md versionné ne décrit que le répertoire de données par défaut ; un
# autre répertoire (F1_DONNEES) reçoit le sien, pour ne pas écraser celui du dépôt.
SORTIE = RACINE / "SOURCES.md" if DONNEES == (RACINE / "donnees").resolve() else DONNEES / "SOURCES.md"

CONDITIONS = "https://raw.githubusercontent.com/jolpica/jolpica-f1/main/TERMS.md"
CONDITIONS_PAGE = "https://github.com/jolpica/jolpica-f1/blob/main/TERMS.md"


def lire_conditions() -> dict:
    try:
        req = urllib.request.Request(CONDITIONS, headers={"User-Agent": USER_AGENT})
        corps = urllib.request.urlopen(req, timeout=30).read()
    except OSError as e:
        return {"licence": None, "maj": None, "sha256": None, "erreur": str(e)}
    texte = corps.decode("utf-8", errors="replace")
    licence = re.search(r"licensed under ([^\n]+?\([^)\n]+\))", texte)
    maj = re.search(r"Last updated:\s*([^_\n]+)", texte)
    return {
        "licence": licence[1].strip() if licence else None,
        "maj": maj[1].strip() if maj else None,
        "sha256": hashlib.sha256(corps).hexdigest(),
        "erreur": None if licence else "mention de licence introuvable dans les conditions",
    }


def main() -> int:
    metas = sorted(CACHE.rglob("*.meta.json")) if CACHE.is_dir() else []
    if not metas:
        print("Cache vide : lancer d'abord extraire.py.", file=sys.stderr)
        return 1

    lignes, anomalies = [], []
    par_groupe: dict[str, list] = defaultdict(list)
    for m in metas:
        meta = json.loads(m.read_text(encoding="utf-8"))
        donnees = m.with_name(m.name.replace(".meta.json", ".json"))
        if not donnees.exists():
            anomalies.append(f"{donnees.relative_to(CACHE).as_posix()} : fichier absent")
            continue
        sha = hashlib.sha256(donnees.read_bytes()).hexdigest()
        if sha != meta["sha256"]:
            anomalies.append(f"{donnees.relative_to(CACHE).as_posix()} : empreinte modifiée depuis l'extraction")
        relatif = donnees.relative_to(CACHE).as_posix()
        groupe = relatif.split("/")[0]
        par_groupe[groupe].append(meta["recupere_le"])
        lignes.append((relatif, meta["url"], meta["sha256"], meta["recupere_le"]))

    c = lire_conditions()
    dates = sorted(l[3] for l in lignes)
    licence = c["licence"] or "**NON VÉRIFIÉE** — conditions illisibles, voir anomalies"

    sortie = [
        "# Sources des données",
        "",
        "> Fichier généré par `python manifeste.py` — ne pas modifier à la main.",
        "",
        "Les données ne sont **pas** versionnées : `donnees/` est exclu par `.gitignore`.",
        "Pour les reconstituer depuis la source officielle : `python extraire.py`.",
        "",
        "| Champ | Valeur |",
        "|---|---|",
        "| Identifiant | <https://api.jolpi.ca/ergast/f1/> |",
        "| Titre | Jolpica-F1 API — points d'accès compatibles Ergast |",
        "| Éditeur | Projet Jolpica-F1 (bénévoles), <https://github.com/jolpica/jolpica-f1> |",
        f"| Licence | {licence} — <https://creativecommons.org/licenses/by-nc-sa/4.0/> |",
        f"| Conditions d'utilisation | <{CONDITIONS_PAGE}> (mise à jour : {c['maj'] or 'inconnue'}, "
        f"SHA-256 `{(c['sha256'] or 'n/d')[:16]}…`) |",
        "| Attribution | L'éditeur n'impose pas de formule. Mention retenue par ce projet : "
        "« Données : Jolpica-F1 (api.jolpi.ca), licence CC BY-NC-SA 4.0 » |",
        "| Usage | Non commercial uniquement (clause NC) ; toute œuvre dérivée partagée "
        "sous la même licence (clause SA) |",
        "| URL de téléchargement | Une par fichier, voir ci-dessous ; script : `extraire.py` |",
        f"| Date de consultation | du {dates[0]} au {dates[-1]} (UTC) |",
        f"| Fichiers | {len(lignes)} réponses JSON |",
        "",
    ]
    if c["erreur"] or anomalies:
        sortie += ["## Anomalies", ""]
        if c["erreur"]:
            sortie.append(f"- Conditions d'utilisation : {c['erreur']}")
        sortie += [f"- {a}" for a in anomalies]
        sortie.append("")
    sortie += ["## Fichiers", "",
               "Chemin relatif à `donnees/brut/`. Empreinte : SHA-256 de la réponse brute.", "",
               "| Fichier | URL | SHA-256 | Récupéré le |", "|---|---|---|---|"]
    sortie += [f"| `{f}` | <{u}> | `{s}` | {d} |" for f, u, s, d in lignes]

    SORTIE.write_text("\n".join(sortie) + "\n", encoding="utf-8")
    print(f"{SORTIE.name} ({SORTIE.parent}) : {len(lignes)} fichier(s), {len(anomalies)} anomalie(s), "
          f"licence {'relue' if c['licence'] else 'NON VÉRIFIÉE'}")
    return 1 if anomalies or c["erreur"] else 0


if __name__ == "__main__":
    sys.exit(main())

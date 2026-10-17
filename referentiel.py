"""Pays et nationalités : libellés de l'API -> codes ISO 3166-1 alpha-3.

Deux sources, aucune recopiée dans le dépôt :
  * referentiel/pays.csv (produit par le projet, versionné) : à chaque libellé de
    l'API (« UK », « British »…) son code ISO 3166 alpha-3 et, pour une nationalité,
    le gentilé français ;
  * iso-codes (projet Debian, LGPL-2.1-or-later), version épinglée, téléchargé
    dans donnees/referentiels/ : la liste officielle des codes (3166-1, et 3166-3
    pour les codes retirés comme DDR ou RHO) et les noms français des pays.

Chaque code de la table est vérifié contre iso-codes : un code inexistant, ou un
libellé de l'API absent de la table, arrête la transformation (DonneeInvalide)
au lieu de produire un pays deviné.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import logging
import re
import urllib.request

from commun import DONNEES, RACINE, USER_AGENT

log = logging.getLogger("f1.referentiel")

ISO_VERSION = "v4.20.1"
ISO_DEPOT = "https://salsa.debian.org/iso-codes-team/iso-codes"
ISO_FICHIERS = {
    "iso_3166-1.json": "data/iso_3166-1.json",
    "iso_3166-3.json": "data/iso_3166-3.json",
    "iso_3166-1.fr.po": "iso_3166-1/fr.po",
    "iso_3166-3.fr.po": "iso_3166-3/fr.po",
}
DOSSIER = DONNEES / "referentiels" / f"iso-codes-{ISO_VERSION}"
TABLE = RACINE / "referentiel" / "pays.csv"


class ReferentielInvalide(ValueError):
    pass


def assurer() -> int:
    """Télécharge les fichiers iso-codes absents. Renvoie le nombre de téléchargements."""
    DOSSIER.mkdir(parents=True, exist_ok=True)
    n = 0
    for local, distant in ISO_FICHIERS.items():
        fichier = DOSSIER / local
        if fichier.exists():
            continue
        url = f"{ISO_DEPOT}/-/raw/{ISO_VERSION}/{distant}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        corps = urllib.request.urlopen(req, timeout=60).read()
        provisoire = fichier.with_name(fichier.name + ".tmp")
        provisoire.write_bytes(corps)
        provisoire.replace(fichier)
        (DOSSIER / f"{local}.meta.json").write_text(json.dumps({
            "url": url,
            "recupere_le": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "sha256": hashlib.sha256(corps).hexdigest(),
            "octets": len(corps),
        }, indent=2), encoding="utf-8")
        log.info("  iso-codes %s : %s téléchargé (%d octets)", ISO_VERSION, local, len(corps))
        n += 1
    return n


def _po(chemin) -> dict[str, str]:
    """msgid -> msgstr d'un fichier .po (lignes de continuation comprises)."""
    traductions, cle, valeur, champ = {}, None, None, None
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        m = re.match(r'(msgid|msgstr) "(.*)"$', ligne)
        if m:
            if m[1] == "msgid":
                if cle and valeur:
                    traductions[cle] = valeur
                cle, valeur, champ = m[2], None, "msgid"
            else:
                valeur, champ = m[2], "msgstr"
        elif ligne.startswith('"') and champ:
            suite = ligne[1:-1]
            if champ == "msgid":
                cle += suite
            else:
                valeur += suite
    if cle and valeur:
        traductions[cle] = valeur
    return {k: v.replace('\\"', '"') for k, v in traductions.items()}


def _iso() -> dict[str, dict]:
    manquants = [f for f in ISO_FICHIERS if not (DOSSIER / f).exists()]
    if manquants:
        raise ReferentielInvalide(f"fichiers iso-codes absents de {DOSSIER} : {manquants} — "
                                  "lancer l'extraction (pipeline.py) pour les télécharger")
    codes = {}
    fr1, fr3 = _po(DOSSIER / "iso_3166-1.fr.po"), _po(DOSSIER / "iso_3166-3.fr.po")
    for x in json.loads((DOSSIER / "iso_3166-1.json").read_text(encoding="utf-8"))["3166-1"]:
        nom = x.get("common_name") or x["name"]
        codes[x["alpha_3"]] = {"name": nom, "officialName": x.get("official_name") or x["name"],
                               "nom": fr1.get(nom) or fr1.get(x["name"]), "withdrawn": False}
    for x in json.loads((DOSSIER / "iso_3166-3.json").read_text(encoding="utf-8"))["3166-3"]:
        if "alpha_3" in x and x["alpha_3"] not in codes:
            codes[x["alpha_3"]] = {"name": x["name"], "officialName": x["name"],
                                   "nom": fr3.get(x["name"]), "withdrawn": True,
                                   "withdrawalDate": x.get("withdrawal_date")}
    return codes


_cache: tuple | None = None


def correspondances() -> tuple[dict[tuple[str, str], str], dict[str, dict]]:
    """((role, libellé API) -> iso3, iso3 -> propriétés du nœud). Vérifiée, mise en cache."""
    global _cache
    if _cache is None:
        iso = _iso()
        table, gentiles, inconnus = {}, {}, []
        for ligne in csv.DictReader(TABLE.open(encoding="utf-8"), delimiter=";"):
            code = ligne["iso3"].strip()
            if code not in iso:
                inconnus.append(f"{ligne['libelle_source']} -> {code}")
            table[(ligne["role"], ligne["libelle_source"])] = code
            if ligne["role"] == "nationalite":
                gentiles.setdefault(code, {"nationality": ligne["libelle_source"],
                                           "nationalite": ligne["nationalite_fr"] or None})
        if inconnus:
            raise ReferentielInvalide(f"{TABLE.name} : code(s) absents d'ISO 3166 ({ISO_VERSION}) : {inconnus}")
        noeuds = {code: {**iso[code], **gentiles.get(code, {})} for code in set(table.values())}
        _cache = (table, noeuds)
    return _cache


def iso3(role: str, libelle: str | None, contexte: str) -> str | None:
    """Code d'un libellé de l'API ; None si la source n'en donne pas ; erreur s'il est inconnu."""
    if not libelle:
        return None
    table, _ = correspondances()
    code = table.get((role, libelle))
    if code is None:
        raise ReferentielInvalide(
            f"{contexte} : {role} « {libelle} » absent de {TABLE.relative_to(RACINE)} — "
            "ajouter sa ligne (code vérifié dans ISO 3166) ; aucun code n'est deviné")
    return code

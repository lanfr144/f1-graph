"""Éléments partagés par extraire.py, charger.py et manifeste.py."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

VERSION = "0.1.0"

RACINE = Path(__file__).resolve().parent
# Réponses brutes de l'API, exclues du dépôt (voir .gitignore et SOURCES.md).
CACHE = RACINE / "donnees" / "brut"
SCHEMA = RACINE / "schema"

API = "https://api.jolpi.ca/ergast/f1/"
# L'API exige un User-Agent propre à l'application, versionné.
USER_AGENT = f"f1-graph/{VERSION} Python/{sys.version_info.major}.{sys.version_info.minor}"
# Taille de page maximale acceptée par l'API.
TAILLE_PAGE = 100


def lire_env(chemin: Path = RACINE / ".env") -> None:
    """Charge un fichier KEY=VALUE dans os.environ, sans écraser l'existant."""
    if not chemin.exists():
        return
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, valeur = ligne.split("=", 1)
        os.environ.setdefault(cle.strip(), valeur.strip().strip('"').strip("'"))


def exiger_env(nom: str) -> str:
    valeur = os.environ.get(nom)
    if not valeur:
        raise SystemExit(f"Variable d'environnement manquante : {nom} (voir .env.example)")
    return valeur


def dossier_cache(chemin_api: str) -> Path:
    """'2024/results' -> donnees/brut/2024/results/"""
    return CACHE / chemin_api


def fichier_page(chemin_api: str, offset: int) -> Path:
    return dossier_cache(chemin_api) / f"offset-{offset:06d}.json"


def lire_pages(chemin_api: str) -> list[dict]:
    """Toutes les pages en cache d'un point d'accès, dans l'ordre (contenu MRData)."""
    dossier = dossier_cache(chemin_api)
    if not dossier.is_dir():
        return []
    return [json.loads(f.read_text(encoding="utf-8"))["MRData"]
            for f in sorted(dossier.glob("offset-??????.json"))]  # et non les .meta.json

"""Éléments partagés par extraire.py, charger.py et manifeste.py."""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

VERSION = "0.1.0"

RACINE = Path(__file__).resolve().parent
# Répertoire de travail local, exclu du dépôt (voir .gitignore et SOURCES.md).
# F1_DONNEES permet d'en utiliser un autre (essais, second jeu de données).
DONNEES = Path(os.environ.get("F1_DONNEES") or RACINE / "donnees").resolve()
CACHE = DONNEES / "brut"            # réponses brutes de l'API
JOURNAUX = DONNEES / "journaux"     # journaux et traces d'avancement
ETAT = DONNEES / "etat.json"        # point de reprise de pipeline.py
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


class Verrou:
    """Interdit deux traitements simultanés sur le même répertoire de données.

    Verrou posé par le système d'exploitation sur un fichier ouvert : il tombe
    de lui-même à la fin du processus, même tué — aucun verrou orphelin à nettoyer.
    """

    def __init__(self) -> None:
        self.chemin = DONNEES / "traitement.lock"
        self.fichier = None

    def __enter__(self) -> "Verrou":
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.fichier = open(self.chemin, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                self.fichier.seek(0)
                msvcrt.locking(self.fichier.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fichier.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fichier.close()
            raise SystemExit(f"Un autre traitement utilise déjà {DONNEES} "
                             f"(verrou {self.chemin.name}) : attendre sa fin.") from None
        return self

    def __exit__(self, *exc) -> None:
        if os.name == "nt":
            import msvcrt
            self.fichier.seek(0)
            try:
                msvcrt.locking(self.fichier.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        self.fichier.close()


def journal_console(niveau: int = logging.INFO) -> None:
    """Sortie console sobre pour les scripts lancés seuls (extraire.py, charger.py)."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=niveau, format="%(message)s", stream=sys.stdout)


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

"""Healthcheck du service de chargement : ce que le service rend, pas qu'un processus tourne.

Sain (code 0) si :
  * une exécution est EN COURS et a progressé (etat.json réécrit) depuis moins de
    SANTE_INACTIVITE_MAX_S secondes — une étape peut attendre le quota de l'API ;
  * ou la dernière exécution est TERMINÉE depuis moins de SANTE_AGE_MAX_S secondes,
    Neo4j répond et contient le graphe F1.
Avec --web (interface) : sain si Neo4j répond et contient le graphe.
Malade (code 1) sinon, avec une ligne qui dit pourquoi (visible par
`docker inspect --format '{{json .State.Health}}'`).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time

from commun import ETAT, exiger_env, lire_env


def graphe_present() -> tuple[bool, str]:
    import charger
    try:
        driver, base = charger.connexion()
        with driver, driver.session(database=base) as s:
            present = s.run("RETURN EXISTS { MATCH (:Race)<-[:IN_RACE]-(:RaceResult) } AS ok").single()["ok"]
    except Exception as e:
        return False, f"Neo4j injoignable : {e}"
    if not present:
        return False, "Neo4j répond mais ne contient aucun résultat de course"
    return True, "Neo4j répond et contient le graphe"


def verdict() -> tuple[bool, str]:
    lire_env()
    inactivite_max = int(exiger_env("SANTE_INACTIVITE_MAX_S"))
    age_max = int(exiger_env("SANTE_AGE_MAX_S"))
    if not ETAT.exists():
        return False, f"aucune exécution enregistrée ({ETAT} absent) : le chargement initial n'a pas démarré"
    etat = json.loads(ETAT.read_text(encoding="utf-8"))
    ex = etat.get("execution", {})
    statut = ex.get("statut")
    if statut == "en_cours":
        inactif = time.time() - ETAT.stat().st_mtime
        if inactif > inactivite_max:
            return False, f"exécution {ex.get('id')} en cours mais sans progrès depuis {int(inactif)} s"
        faites = sum(1 for e in etat.get("etapes", {}).values() if e.get("statut") == "fait")
        return True, f"exécution {ex.get('id')} en cours, {faites} étape(s) faite(s)"
    if statut != "terminee":
        echecs = [n for n, e in etat.get("etapes", {}).items() if e.get("statut") in ("echec", "bloquee")]
        return False, f"dernière exécution {ex.get('id')} : {statut} ; étapes en défaut : {echecs[:5]}"
    age = (dt.datetime.now().astimezone() - dt.datetime.fromisoformat(ex["fin"])).total_seconds()
    if age > age_max:
        return False, f"dernière exécution réussie il y a {int(age)} s (> {age_max}) : le cron ne tourne plus ?"
    ok, message = graphe_present()
    if not ok:
        return False, message
    return True, f"dernière exécution {ex.get('id')} réussie il y a {int(age)} s, graphe présent"


if __name__ == "__main__":
    # --web : healthcheck de l'interface, qui ne dépend que de la base.
    ok, message = graphe_present() if "--web" in sys.argv else verdict()
    print(("SAIN : " if ok else "MALADE : ") + message)
    sys.exit(0 if ok else 1)

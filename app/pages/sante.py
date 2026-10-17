"""Santé : état du chargement, journal, contrôles de la base."""
import json
import subprocess
import sys

import pandas as pd
import streamlit as st

from outils import RACINE, erreur_connexion, requete

from commun import ETAT, JOURNAUX

st.title("Santé du chargement")

if not ETAT.exists():
    st.warning(f"Aucune exécution enregistrée ({ETAT}).")
else:
    etat = json.loads(ETAT.read_text(encoding="utf-8"))
    ex = etat.get("execution", {})
    statut = ex.get("statut")
    couleur = {"terminee": "green", "en_cours": "blue"}.get(statut, "red")
    st.markdown(f"Dernière exécution **{ex.get('id')}** : :{couleur}-badge[{statut}] — débutée {ex.get('debut')}"
                + (f", finie {ex['fin']}" if ex.get("fin") else "") + f" — paramètres `{ex.get('parametres')}`")
    etapes = pd.DataFrame([{"etape": k, **v} for k, v in etat.get("etapes", {}).items()])
    if not etapes.empty:
        c = st.columns(4)
        for i, s in enumerate(("fait", "en_cours", "echec", "bloquee")):
            c[i].metric(s, int((etapes["statut"] == s).sum()))
        defauts = etapes[etapes["statut"].isin(["echec", "bloquee", "interrompue"])]
        if not defauts.empty:
            st.error("Étapes en défaut")
            st.dataframe(defauts, hide_index=True, use_container_width=True)
        with st.expander("Toutes les étapes"):
            st.dataframe(etapes, hide_index=True, use_container_width=True)

journaux = sorted(JOURNAUX.glob("pipeline-*.log")) if JOURNAUX.is_dir() else []
if journaux:
    dernier = journaux[-1]
    lignes = dernier.read_text(encoding="utf-8", errors="replace").splitlines()
    problemes = [l for l in lignes if " ERROR " in l or " WARNING " in l]
    st.subheader(f"Journal {dernier.name}")
    if problemes:
        st.warning(f"{len(problemes)} avertissement(s) ou erreur(s)")
        st.code("\n".join(problemes[-40:]), language="log")
    with st.expander("Fin du journal (80 lignes)"):
        st.code("\n".join(lignes[-80:]), language="log")

st.subheader("Base")
try:
    st.dataframe(requete("""
        MATCH (r:Race) WHERE EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
        RETURN min(r.season) AS premiere_saison, max(r.season) AS derniere_saison,
               count(r) AS grands_prix_disputes, max(r.date) AS dernier_grand_prix""",
                         titre="Requête : couverture des données"), hide_index=True)
except Exception as e:
    erreur_connexion(e)

if st.button("Lancer la vérification complète (verifier.py, environ une minute)"):
    with st.spinner("Vérification…"):
        sortie = subprocess.run([sys.executable, str(RACINE / "verifier.py")], capture_output=True,
                                text=True, cwd=RACINE, encoding="utf-8", errors="replace")
    (st.success if sortie.returncode == 0 else st.error)(
        "Aucun écart" if sortie.returncode == 0 else f"Écarts détectés (code {sortie.returncode})")
    st.code(sortie.stdout[-15000:] + sortie.stderr[-3000:], language="log")

"""Briques communes de l'interface web : connexion, exécution affichée, graphes interactifs."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as composants

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

# Couleurs par nature de nœud, reprises dans toutes les vues.
COULEURS = {
    "Driver": "#378ADD", "Constructor": "#D85A30", "Race": "#7F77DD", "Season": "#888780",
    "Circuit": "#1D9E75", "Country": "#BA7517", "Status": "#B4B2A9",
    "RaceResult": "#AFA9EC", "SprintResult": "#CECBF6", "QualifyingResult": "#9FE1CB",
    "PitStop": "#F0997B", "LapTime": "#F5C4B3",
}


@st.cache_resource(show_spinner=False)
def connexion():
    import charger
    return charger.connexion()


def session():
    driver, base = connexion()
    return driver.session(database=base)


def natif(valeur):
    """Types temporels de Neo4j -> types Python (Arrow ne connaît pas neo4j.time.Date)."""
    if isinstance(valeur, list):
        return [natif(v) for v in valeur]
    return valeur.to_native() if hasattr(valeur, "to_native") else valeur


def tableau(lignes: list[dict], colonnes=None) -> pd.DataFrame:
    return pd.DataFrame([{k: natif(v) for k, v in l.items()} for l in lignes], columns=colonnes)


def sans_dollar(texte: str) -> str:
    """Le Markdown de Streamlit lit « $…$ » comme une formule : on échappe les paramètres Cypher."""
    return texte.replace("$", "\\$")


def requete(cypher: str, titre: str = "Requête Cypher exécutée", **params) -> pd.DataFrame:
    """Exécute une requête de lecture et l'affiche (texte et paramètres) dans un volet."""
    with st.expander(titre, expanded=False):
        st.code(cypher.strip(), language="cypher")
        if params:
            st.caption(sans_dollar("Paramètres : " + ", ".join(f"${k} = {v!r}" for k, v in params.items())))
    with session() as s:
        return tableau([dict(r) for r in s.run(cypher, params)])


def graphe(noeuds: dict[str, dict], aretes: list[tuple], hauteur: int = 560) -> None:
    """Graphe interactif (déplacer, zoomer, survoler) : vis-network embarqué par pyvis."""
    from pyvis.network import Network
    net = Network(height=f"{hauteur}px", width="100%", cdn_resources="in_line", directed=False)
    net.barnes_hut(gravity=-6000, spring_length=140)
    for ident, n in noeuds.items():
        net.add_node(ident, label=n.get("label", ident), title=n.get("titre", n.get("label", ident)),
                     color=n.get("couleur", "#888780"), shape=n.get("forme", "dot"),
                     size=n.get("taille", 18), font={"size": 16})
    vues = set()
    for a, b, *suite in aretes:
        if (a, b) in vues or (b, a) in vues:  # une arête par paire
            continue
        vues.add((a, b))
        options = suite[0] if suite else {}
        net.add_edge(a, b, title=options.get("titre", ""), label=options.get("label", ""),
                     width=options.get("largeur", 1.5), color=options.get("couleur", "#B4B2A9"))
    composants.html(net.generate_html(notebook=False), height=hauteur + 20)


def erreur_connexion(e: Exception) -> None:
    st.error(f"Neo4j injoignable : {e}")
    st.info("Vérifier que le service neo4j est sain : docker compose ps")

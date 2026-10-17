"""Interface web du graphe F1 : streamlit run app/accueil.py"""
import streamlit as st

import outils  # noqa: F401  (chemin du projet)

st.set_page_config(page_title="Graphe F1", page_icon="🏁", layout="wide")

pages = st.navigation([
    st.Page("pages/questions.py", title="Questions de la rédaction", icon=":material/quiz:", default=True),
    st.Page("pages/pilote.py", title="Explorer un pilote", icon=":material/person_search:"),
    st.Page("pages/modele.py", title="Modèle du graphe", icon=":material/hub:"),
    st.Page("pages/sante.py", title="Santé du chargement", icon=":material/monitor_heart:"),
])
pages.run()

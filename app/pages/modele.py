"""Le modèle : étiquettes, relations, volumes, contraintes et index — lus dans la base."""
import streamlit as st

from outils import COULEURS, RACINE, erreur_connexion, graphe, requete

import charger

st.title("Modèle du graphe")

# Schéma déclaré par le projet : (étiquette de départ, relation, étiquette d'arrivée).
SCHEMA = [
    ("Race", "IN_SEASON", "Season"), ("Race", "HELD_AT", "Circuit"),
    ("Circuit", "LOCATED_IN", "Country"), ("Driver", "HAS_NATIONALITY", "Country"),
    ("Constructor", "HAS_NATIONALITY", "Country"),
    ("RaceResult", "IN_RACE", "Race"), ("RaceResult", "OF_DRIVER", "Driver"),
    ("RaceResult", "FOR_CONSTRUCTOR", "Constructor"), ("RaceResult", "WITH_STATUS", "Status"),
    ("SprintResult", "IN_RACE", "Race"), ("SprintResult", "OF_DRIVER", "Driver"),
    ("SprintResult", "FOR_CONSTRUCTOR", "Constructor"), ("SprintResult", "WITH_STATUS", "Status"),
    ("QualifyingResult", "IN_RACE", "Race"), ("QualifyingResult", "OF_DRIVER", "Driver"),
    ("QualifyingResult", "FOR_CONSTRUCTOR", "Constructor"),
    ("PitStop", "IN_RACE", "Race"), ("PitStop", "OF_DRIVER", "Driver"),
    ("LapTime", "IN_RACE", "Race"), ("LapTime", "OF_DRIVER", "Driver"),
    ("Driver", "DROVE_FOR", "Constructor"), ("Driver", "RANKED_IN", "Season"),
    ("Constructor", "RANKED_IN", "Season"), ("Driver", "TEAMMATE_OF", "Driver"),
]

try:
    comptes = requete(" UNION ALL ".join(
        f"MATCH (n:{l}) RETURN '{l}' AS etiquette, count(n) AS n" for l in charger.LABELS
        if l != "Nationality"), titre="Requête : nombre de nœuds par étiquette")
    liens = requete(" UNION ALL ".join(
        f"MATCH (:{a})-[r:{t}]->(:{b}) RETURN '{a}' AS a, '{t}' AS type, '{b}' AS b, count(r) AS n"
        for a, t, b in SCHEMA), titre="Requête : nombre de relations par type et par extrémités")
except Exception as e:
    erreur_connexion(e)
    st.stop()

n = dict(zip(comptes["etiquette"], comptes["n"]))
noeuds = {l: {"label": f"{'Country:Nationality' if l == 'Country' else l}\n{n.get(l, 0):,}".replace(",", " "),
              "couleur": COULEURS.get(l, "#888780"), "forme": "box", "titre": f"{n.get(l, 0)} nœud(s)"}
          for l in n}
aretes = [(l["a"], l["b"], {"label": f"{l['type']} ({l['n']:,})".replace(",", " "), "titre": l["type"]})
          for _, l in liens.iterrows() if l["a"] != l["b"]]
st.caption("Chaque boîte est une étiquette, chaque lien un type de relation, avec les volumes actuels. "
           "Pays et nationalité partagent un même nœud ISO 3166 alpha-3. "
           "TEAMMATE_OF (de pilote à pilote) est dérivée de DROVE_FOR.")
graphe(noeuds, aretes, hauteur=640)

c1, c2 = st.columns(2)
with c1:
    st.subheader("Contraintes")
    st.dataframe(requete("SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties "
                         "RETURN name, type, labelsOrTypes, properties ORDER BY name",
                         titre="Requête : contraintes"), hide_index=True, use_container_width=True)
with c2:
    st.subheader("Index")
    st.dataframe(requete("SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties "
                         "WHERE type <> 'LOOKUP' RETURN name, type, state, labelsOrTypes, properties ORDER BY name",
                         titre="Requête : index"), hide_index=True, use_container_width=True)

doc = RACINE / "docs" / "modele-graphe.md"
if doc.exists():
    st.subheader("Documentation")
    st.markdown(doc.read_text(encoding="utf-8").split("```mermaid")[0])

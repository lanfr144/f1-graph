"""Un pilote : carrière, classements, et réseau de coéquipiers interactif."""
import altair as alt
import streamlit as st

from outils import COULEURS, erreur_connexion, graphe, requete

st.title("Explorer un pilote")

try:
    pilotes = requete("""
        MATCH (d:Driver) WHERE EXISTS { (d)<-[:OF_DRIVER]-(:RaceResult) }
        RETURN d.driverId AS id, d.fullName AS nom,
               COLLECT { MATCH (d)-[f:DROVE_FOR]->() RETURN max(f.season) }[0] AS derniere
        ORDER BY derniere DESC, nom""", titre="Requête : liste des pilotes ayant couru")
except Exception as e:
    erreur_connexion(e)
    st.stop()

pilotes = pilotes.drop_duplicates("id")
choix = st.selectbox("Pilote", pilotes["id"], format_func=lambda i: pilotes.set_index("id").loc[i, "nom"])

fiche = requete("""
    MATCH (d:Driver {driverId: $id})
    OPTIONAL MATCH (d)-[:HAS_NATIONALITY]->(n:Nationality)
    RETURN d.fullName AS nom, d.code AS code, d.dateOfBirth AS naissance, n.iso3 AS iso3,
           n.nationalite AS nationalite, d.url AS wikipedia,
           COUNT { (d)<-[:OF_DRIVER]-(:RaceResult) } AS departs,
           COUNT { (d)<-[:OF_DRIVER]-(:RaceResult {position: 1}) } AS victoires,
           COUNT { (d)-[k:RANKED_IN]->(:Season) WHERE k.position = 1 } AS titres""",
                titre="Requête : fiche du pilote", id=choix).iloc[0]
st.subheader(f"{fiche['nom']} {('(' + fiche['code'] + ')') if fiche['code'] else ''}")
c = st.columns(5)
c[0].metric("Nationalité", f"{fiche['nationalite'] or '—'} ({fiche['iso3'] or '?'})")
c[1].metric("Départs", int(fiche["departs"]))
c[2].metric("Victoires", int(fiche["victoires"]))
c[3].metric("Titres", int(fiche["titres"]))
c[4].metric("Naissance", str(fiche["naissance"] or "—"))
if fiche["wikipedia"]:
    st.caption(f"[Wikipédia]({fiche['wikipedia']})")

saisons = requete("""
    MATCH (d:Driver {driverId: $id})-[k:RANKED_IN]->(s:Season)
    RETURN s.year AS saison, k.position AS rang, k.points AS points, k.wins AS victoires
    ORDER BY saison""", titre="Requête : classements finaux par saison", id=choix)
if not saisons.empty:
    st.altair_chart(alt.Chart(saisons).mark_line(point=True, color=COULEURS["Driver"]).encode(
        x=alt.X("saison:O", title=None), y=alt.Y("rang:Q", scale=alt.Scale(reverse=True), title="rang final"),
        tooltip=list(saisons.columns)), use_container_width=True)

st.subheader("Réseau des coéquipiers")
profondeur = st.radio("Profondeur", [1, 2], horizontal=True,
                      format_func=lambda p: "coéquipiers" if p == 1 else "coéquipiers et leurs coéquipiers")
reseau = requete("""
    MATCH (d:Driver {driverId: $id})
    MATCH p = (d)-[:TEAMMATE_OF*1..2]-(x:Driver)
    WHERE length(p) <= $profondeur
    UNWIND relationships(p) AS t
    WITH DISTINCT t
    RETURN startNode(t).driverId AS a, startNode(t).fullName AS nom_a,
           endNode(t).driverId AS b, endNode(t).fullName AS nom_b,
           t.seasons AS saisons, t.constructors AS ecuries""",
                 titre="Requête : réseau TEAMMATE_OF", id=choix, profondeur=profondeur)
noeuds, aretes = {}, []
for _, l in reseau.iterrows():
    for ident, nom in ((l["a"], l["nom_a"]), (l["b"], l["nom_b"])):
        noeuds.setdefault(ident, {"label": nom, "couleur": COULEURS["Driver"], "taille": 14})
    aretes.append((l["a"], l["b"], {"titre": f"{', '.join(l['ecuries'])} — {sorted(l['saisons'])}",
                                     "largeur": 1 + len(l["saisons"])}))
if choix in noeuds:
    noeuds[choix].update(couleur="#BA7517", taille=30)
st.caption(f"{len(noeuds)} pilote(s), {len(aretes)} lien(s). Épaisseur = saisons partagées ; survoler un lien "
           "pour l'écurie et les saisons.")
graphe(noeuds, aretes, hauteur=620)

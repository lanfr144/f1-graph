"""Les seize questions : prérequêtes, requête, réponse en tableau et en graphique."""
import altair as alt
import pandas as pd
import streamlit as st

from outils import COULEURS, erreur_connexion, graphe, sans_dollar, session, tableau

import questions as qmod

st.title("Questions de la rédaction")
st.caption("Chaque question cherche d'abord dans la base les valeurs pour lesquelles elle a une réponse "
           "(prérequêtes), puis exécute sa requête. Toutes les requêtes exécutées sont affichées.")

QUESTIONS = qmod.lire_questions()


def couverture(q: dict) -> str:
    texte = q["notes"][0] if q["notes"] else ""
    for niveau, badge in (("NON COUVERTE", ":red-badge[non couverte]"), ("PARTIELLE", ":orange-badge[partielle]"),
                          ("complète", ":green-badge[complète]"), ("Doublon", ":gray-badge[doublon]")):
        if niveau in texte:
            return badge
    return ""


choix = st.selectbox(
    "Question", sorted(QUESTIONS),
    format_func=lambda n: f"Q{n} — {QUESTIONS[n]['titre']}")
q = QUESTIONS[choix]
st.subheader(f"Q{choix} {couverture(q)}")
st.markdown(f"**{q['titre']}**")
st.info(sans_dollar(" ".join(q["notes"])))

if not q["requete"]:
    st.warning("Pas de requête : la répondre exigerait des données que la source ne contient pas.")
    st.stop()

# Paramètres modifiables : toute valeur saisie l'emporte sur la valeur fixe ou trouvée.
with st.expander("Modifier les paramètres (expressions Cypher : 'alonso', date('2026-10-01'), 3…)"):
    surcharges = {}
    colonnes = st.columns(3)
    for i, (nom, defaut) in enumerate(q["params"].items()):
        valeur = colonnes[i % 3].text_input(f"${nom}", value=defaut, key=f"{choix}-{nom}").strip()
        if valeur and valeur != defaut:
            surcharges[nom] = valeur
    autres = st.text_area("Paramètres trouvés par les prérequêtes, à remplacer (une ligne « nom = expression »)",
                          placeholder="a = 'alonso'\nb = 'hamilton'", key=f"{choix}-autres")
    for ligne in autres.splitlines():
        if "=" in ligne:
            nom, _, expr = ligne.partition("=")
            surcharges[nom.strip().lstrip("$")] = expr.strip()

try:
    with session() as s, st.spinner("Exécution des requêtes…"):
        r = qmod.executer_question(s, q, surcharges)
except Exception as e:
    if "Unable to" in str(e) or "connect" in str(e).lower():
        erreur_connexion(e)
    else:
        st.error(f"Échec de la requête : {e}")
    st.stop()

for pre in r["prerequetes"]:
    with st.expander(f"Prérequête — {pre['but']}", expanded=False):
        st.code(pre["cypher"], language="cypher")
    st.caption(sans_dollar("Valeurs trouvées : " + ", ".join(
        f"**${k}** = {v}" + (" *(remplacée)*" if k in pre["remplacees"] else "") for k, v in pre["valeurs"].items())))
with st.expander("Requête exécutée", expanded=True):
    st.code(r["cypher"], language="cypher")
    st.caption(sans_dollar("Paramètres : " + ", ".join(f"${k} = {v}" for k, v in r["params"].items())))


def plan_dot(plan: dict) -> str:
    """Plan d'exécution de Neo4j (EXPLAIN) en Graphviz : un nœud par opérateur, avec ses
    détails (motif parcouru, prédicat de filtre, index utilisé…), de la lecture au résultat."""
    def echapper(t: str) -> str:
        return t.replace("\\", "\\\\").replace('"', '\\"')

    lignes, compteur = ['digraph plan {', '  rankdir=BT; node [shape=box, style="rounded,filled", '
                        'fontname="Helvetica", fontsize=10];', '  edge [color="#888780"];'], [0]

    def visiter(op: dict) -> str:
        compteur[0] += 1
        ident = f"o{compteur[0]}"
        nom = op.get("operatorType", "?").split("@")[0]
        details = str(op.get("args", op.get("arguments", {})).get("Details", ""))
        details = details if len(details) <= 160 else details[:157] + "…"
        filtre = nom in ("Filter", "NodeIndexSeek", "NodeUniqueIndexSeek", "DirectedRelationshipIndexSeek",
                         "NodeByLabelScan", "Limit", "Top", "Sort", "Expand(All)", "Expand(Into)")
        couleur = "#FAEEDA" if nom == "Filter" else "#E6F1FB" if "Index" in nom else "#F1EFE8"
        etiquette = f"{nom}\\n{echapper(details)}" if details else nom
        lignes.append(f'  {ident} [label="{etiquette}", fillcolor="{couleur}"' + (', penwidth=2' if filtre else '') + '];')
        for enfant in op.get("children", []):
            lignes.append(f"  {visiter(enfant)} -> {ident};")
        return ident

    visiter(plan)
    lignes.append("}")
    return "\n".join(lignes)


with st.expander("Comprendre la requête : étapes et filtres", expanded=False):
    if q["etapes"]:
        st.markdown("Chaque boîte est une étape : ce qu'elle **parcourt** dans le graphe (en "
                    "police fixe), puis les **filtres** appliqués (en rouge).")
        st.graphviz_chart(qmod.explication_dot(q), use_container_width=True)
    try:
        with session() as s:
            plan = s.run("EXPLAIN " + r["cypher"], r["params"]).consume().plan
        st.markdown("**Plan d'exécution de Neo4j** (`EXPLAIN`) : ce que le moteur fait réellement, "
                    "de bas en haut. En orange, les opérateurs `Filter` et leur prédicat ; en bleu, "
                    "les lectures par index.")
        st.graphviz_chart(plan_dot(plan), use_container_width=True)
    except Exception as e:  # le plan est une aide, pas une condition de la réponse
        st.caption(f"Plan d'exécution indisponible : {e}")

df = tableau(r["lignes"], r["colonnes"])
if df.empty:
    if choix == 6:
        st.warning("Aucune course à venir n'implique un pilote ou une écurie suivis : la rédaction "
                   "déclare ses suivis dans referentiel/suivis.csv (type ; identifiant ; remarque).")
    else:
        st.warning("Aucune ligne : la base ne contient pas de réponse pour ces paramètres.")
    st.stop()


# --- Visualisations propres à chaque question -----------------------------------

def barres(data, x, y, titre, couleur="#378ADD", tri="-x"):
    graphique = alt.Chart(data).mark_bar(color=couleur).encode(
        x=alt.X(x, title=titre), y=alt.Y(y, sort=tri, title=None), tooltip=list(data.columns))
    st.altair_chart(graphique, use_container_width=True)


def noeud(label, nature, **opts):
    return {"label": label, "couleur": COULEURS.get(nature, "#888780"), **opts}


st.subheader("Réponse")
if choix == 1:
    for _, ligne in df.iterrows():
        faits = ligne["faits_marquants"] or ["aucun fait marquant détecté"]
        with st.container(border=True):
            st.markdown(f"### {ligne['grand_prix']} — {ligne['date']}")
            st.markdown(f"**Vainqueur** : {ligne['vainqueur']} · **Leader du championnat** : "
                        f"{ligne['leader_du_championnat']} · {ligne['circuit']}")
            st.markdown(" ".join(f":orange-badge[{f}]" for f in faits))
            res = pd.DataFrame([x.split(" ", 1) for x in ligne["participants_et_resultats"]],
                               columns=["position", "pilote, écurie, points, statut"])
            st.dataframe(res, hide_index=True, use_container_width=True, height=280)
elif choix == 2:
    top = df.head(15).copy()
    top["duel"] = top["pilote_a"] + " / " + top["pilote_b"]
    long = top.melt(id_vars=["duel"], value_vars=["devant_a", "devant_b"], var_name="qui", value_name="nombre")
    long["qui"] = long["qui"].map({"devant_a": "le premier devant", "devant_b": "le second devant"})
    st.altair_chart(alt.Chart(long).mark_bar().encode(
        x=alt.X("nombre", stack="normalize", title="part des face-à-face"),
        y=alt.Y("duel", sort=None, title=None), color=alt.Color("qui", title=None),
        tooltip=["duel", "qui", "nombre"]), use_container_width=True)
elif choix in (3, 8):
    noeuds, aretes = {}, []
    for _, l in df.iterrows():
        noeuds[l["pilote"]] = noeud(l["pilote"], "Driver", taille=24, titre=f"{l['pilote']} ({l['ecurie']})")
        for k in l["anciennes_ecuries_adverses"]:
            noeuds["k:" + k] = noeud(k, "Constructor", forme="square")
            aretes.append((l["pilote"], "k:" + k, {"titre": "ancienne écurie", "couleur": "#D85A30"}))
        for t in l["anciens_coequipiers_adverses"]:
            noeuds.setdefault(t, noeud(t, "Driver"))
            aretes.append((l["pilote"], t, {"titre": "ancien coéquipier", "couleur": "#378ADD"}))
    st.caption("Pilotes en bleu, écuries en orange : un trait relie un pilote à une ancienne écurie "
               "ou à un ancien coéquipier qu'il affronte désormais.")
    graphe(noeuds, aretes, hauteur=620)
elif choix == 4:
    d = df.dropna(subset=["places_gagnees"]).copy()
    st.altair_chart(alt.Chart(d).mark_bar().encode(
        x=alt.X("places_gagnees:Q", title="places gagnées (+) ou perdues (−)"),
        y=alt.Y("pilote:N", sort=alt.EncodingSortField("rang_apres"), title=None),
        color=alt.condition("datum.places_gagnees >= 0", alt.value("#1D9E75"), alt.value("#D85A30")),
        tooltip=["pilote", "rang_avant", "rang_apres", "points", "rang_officiel"]), use_container_width=True)
elif choix == 5:
    d = df.copy()
    d["paire"] = d["pilote_a"] + " / " + d["pilote_b"]
    st.caption("Années pendant lesquelles les deux pilotes appartenaient en même temps à la même académie.")
    st.altair_chart(alt.Chart(d).mark_bar().encode(
        x=alt.X("ensemble_de:Q", title="années", scale=alt.Scale(zero=False)), x2="ensemble_jusqu_a:Q",
        y=alt.Y("paire:N", sort=None, title=None), color=alt.Color("academie:N", title="académie"),
        tooltip=["paire", "academie", "ensemble_de", "ensemble_jusqu_a", "annees_communes"]),
        use_container_width=True)
elif choix == 6:
    st.dataframe(df, hide_index=True, use_container_width=True)
elif choix == 12:
    noeuds, aretes = {}, []
    for _, l in df.iterrows():
        ident = f"e:{l['encadrement']} {l['saison']}"
        noeuds[ident] = noeud(f"{l['encadrement']} {l['saison']}", "Constructor", forme="square", taille=22)
        for a in l["academies"]:
            noeuds["a:" + a] = noeud(a, "Academy", couleur="#7F77DD", forme="diamond", taille=26)
            aretes.append((ident, "a:" + a, {"couleur": "#7F77DD"}))
    st.caption("En violet, les académies ; en orange, l'écurie d'une saison qui fait courir des pilotes "
               "issus de plusieurs académies, et les relie ainsi.")
    graphe(noeuds, aretes, hauteur=620)
elif choix == 7:
    barres(df, "pct_gagnes:Q", "pilote:N", "% de duels gagnés contre les mieux classés")
elif choix == 9:
    st.dataframe(df, hide_index=True, use_container_width=True)
elif choix == 10:
    l = df.iloc[0]
    c1, c2 = st.columns(2)
    c1.metric("Pilotes isolés si l'écurie disparaît", len(l["pilotes_isoles"]))
    c2.metric("Binômes défaits", l["binomes_defaits"])
    noeuds = {"k": noeud(l["ecurie"], "Constructor", forme="square", taille=30)}
    aretes = []
    for p in l["pilotes_isoles"]:
        noeuds[p] = noeud(p, "Driver")
        aretes.append(("k", p))
    graphe(noeuds, aretes)
elif choix == 11:
    centre = r["params"].get("pilote")
    noeuds = {centre: noeud(centre, "Driver", taille=32, couleur="#BA7517")}
    aretes = []
    for _, l in df.iterrows():
        noeuds[l["pilote_relie"]] = noeud(l["pilote_relie"], "Driver")
        for m in l["par_l_intermediaire_de"]:
            noeuds.setdefault("m:" + m, noeud(m, "Driver", couleur="#7F77DD", titre=f"coéquipier de {centre}"))
            aretes.append((centre, "m:" + m))
            aretes.append(("m:" + m, l["pilote_relie"]))
    st.caption("En violet, les coéquipiers communs ; en bleu, les pilotes reliés indirectement.")
    graphe(noeuds, aretes, hauteur=640)
elif choix == 13:
    d = df.copy()
    d["paire"] = d["ecurie_1"] + " / " + d["ecurie_2"]
    barres(d, "chemins_independants:Q", "paire:N", "chemins indépendants (pilotes et académies)", "#D85A30")
elif choix in (15, 16):
    with session() as s:
        academies = {x["n"] for x in s.run("MATCH (a:Academy) RETURN a.name AS n")}
    noeuds, aretes = {}, []
    for _, l in df.iterrows():
        chaine = l["chaine"] or []
        for i, p in enumerate(chaine):
            extremite = i in (0, len(chaine) - 1)
            est_academie = p in academies
            if est_academie:
                noeuds.setdefault(p, noeud(p, "Academy", couleur="#7F77DD", forme="diamond", taille=22))
            else:
                noeuds.setdefault(p, noeud(p, "Driver", taille=28 if extremite else 16,
                                           couleur="#BA7517" if extremite else COULEURS["Driver"]))
            if i:
                aretes.append((chaine[i - 1], p, {"titre": "académie" if est_academie else "coéquipiers"}))
        if choix == 16:
            for k in l["ecuries_communes"]:
                noeuds["k:" + k] = noeud(k, "Constructor", forme="square")
                aretes += [(l["pilote_a"], "k:" + k, {"couleur": "#D85A30"}),
                           (l["pilote_b"], "k:" + k, {"couleur": "#D85A30"})]
                noeuds.setdefault(l["pilote_a"], noeud(l["pilote_a"], "Driver", taille=28, couleur="#BA7517"))
                noeuds.setdefault(l["pilote_b"], noeud(l["pilote_b"], "Driver", taille=28, couleur="#BA7517"))
    st.caption("Plus courtes chaînes dans le réseau des coéquipiers (TEAMMATE_OF) et des académies "
               "(MEMBER_OF, losanges violets)"
               + (" ; en orange carré, les écuries communes." if choix == 16 else "."))
    graphe(noeuds, aretes, hauteur=600)

with st.expander(f"Tableau complet ({len(df)} ligne(s))", expanded=choix in (9,)):
    st.dataframe(df, hide_index=True, use_container_width=True)

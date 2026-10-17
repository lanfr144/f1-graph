// =============================================================================
//  Graphe F1 — questions de la rédaction
// =============================================================================
//
//  Transposition F1 des questions : événement = Grand Prix, participants et
//  adversaires = pilotes, équipe = écurie (Constructor), coéquipiers = pilotes
//  d'une même écurie LA MÊME SAISON (deux DROVE_FOR de même `season`).
//
//  Le graphe ne contient que ce que publie l'API Jolpica-F1. Il n'a ni
//  entraîneur, ni académie, ni centre de formation, ni sponsor, ni dirigeant,
//  ni fédération, ni rédaction, ni date d'annonce. Chaque question indique sa
//  couverture :
//    complète     la requête répond à la question telle que posée ;
//    partielle    elle répond à la part que les données permettent, et dit
//                 laquelle manque ;
//    non couverte aucune requête : la répondre exigerait d'inventer des liens.
//
//  Paramètres, dans cet ordre :
//    « @param nom = expression »  valeur fixe par défaut (expression Cypher) ;
//    « // --- prérequête »        requête qui CHERCHE dans la base des valeurs pour
//                                 lesquelles la question a une réponse (dernier
//                                 Grand Prix disputé, rivaux pour le titre…) ; ses
//                                 colonnes deviennent des paramètres ;
//    « // --- requête »           la requête qui répond à la question.
//  questions.py enchaîne le tout et affiche chaque requête exécutée ; --param
//  surcharge n'importe quel paramètre :
//      python questions.py 16 --param a="'alonso'" --param b="'hamilton'"
//  Dans Neo4j Browser : exécuter la prérequête, reporter ses valeurs par
//      :param debut => date('2026-09-13')
//  puis exécuter la requête.
//
//  « Entraîneur » n'existe pas en F1 et la source n'en publie pas l'équivalent
//  (directeur d'équipe, ingénieur de course, académie de pilotes) ; Wikidata non
//  plus : une seule des 629 écuries F1 y a un directeur renseigné (vérifié le
//  17 octobre 2026). L'encadrement réellement partagé que les données attestent
//  est l'ÉCURIE D'UNE SAISON : mêmes ingénieurs, même direction, même voiture.
//  C'est ce qui remplace l'entraîneur dans les questions 5 et 10.
//
//  Syntaxe : Cypher 5, Neo4j >= 5.23 (CALL (x) { … }, COLLECT { … }).
//  Chemins entre pilotes : relation dérivée TEAMMATE_OF (voir charger.deriver).
// -----------------------------------------------------------------------------


// === Q1 | What recent event has left its mark on the world of F1 over the last few weeks? Who took part in the races during this event, and what were the results?
// Couverture : complète. Fenêtre : les $semaines semaines qui précèdent le dernier
// Grand Prix disputé, jusqu'à aujourd'hui — elle s'allonge d'elle-même pendant
// l'intersaison. Les Grands Prix de la fenêtre sont classés par nombre de faits
// marquants (première victoire, victoire partie loin, changement de leader au
// championnat, hécatombe d'abandons), puis du plus récent au plus ancien : la
// première ligne est l'événement qui a le plus marqué.
// @param semaines = 4
// @param depart_lointain = 5
// @param abandons_nombreux = 5
// --- prérequête : dernier Grand Prix disputé et fenêtre des dernières semaines
MATCH (r:Race)
WHERE r.date <= date() AND EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
WITH max(r.date) AS dernier
RETURN dernier - duration({weeks: $semaines}) AS debut, date() AS fin, dernier AS dernier_grand_prix;
// --- requête
MATCH (r:Race)-[:HELD_AT]->(c:Circuit)
WHERE r.date >= $debut AND r.date <= $fin AND EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
MATCH (r)<-[:IN_RACE]-(v:RaceResult {position: 1})-[:OF_DRIVER]->(vainqueur:Driver)
CALL (r) {
  // Leader du championnat avant et après la course (points de course et de sprint).
  MATCH (d:Driver)<-[:OF_DRIVER]-(x)-[:IN_RACE]->(p:Race {season: r.season})
  WHERE (x:RaceResult OR x:SprintResult) AND p.round <= r.round
  WITH d, sum(x.points) AS apres,
       sum(CASE WHEN p.round < r.round THEN x.points ELSE 0 END) AS avant
  ORDER BY avant DESC
  WITH collect({pilote: d.fullName, apres: apres}) AS classement
  UNWIND classement AS ligne
  WITH classement[0].pilote AS leader_avant, ligne
  ORDER BY ligne.apres DESC
  RETURN leader_avant, collect(ligne.pilote)[0] AS leader_apres
}
WITH r, c, v, vainqueur, leader_avant, leader_apres,
     NOT EXISTS {
       MATCH (vainqueur)<-[:OF_DRIVER]-(:RaceResult {position: 1})-[:IN_RACE]->(avant:Race)
       WHERE avant.date < r.date
     } AS premiere_victoire,
     COUNT { (r)<-[:IN_RACE]-(x:RaceResult) WHERE x.positionText <> toString(x.position) } AS abandons
WITH r, c, vainqueur, v, leader_apres, abandons,
     [f IN [
        CASE WHEN premiere_victoire THEN 'première victoire de ' + vainqueur.fullName END,
        CASE WHEN v.grid >= $depart_lointain THEN 'victoire partie de la ' + toString(v.grid) + 'e place' END,
        CASE WHEN r.round > 1 AND leader_avant <> leader_apres
             THEN 'nouveau leader du championnat : ' + leader_apres + ' (avant : ' + leader_avant + ')' END,
        CASE WHEN abandons >= $abandons_nombreux THEN toString(abandons) + ' pilotes non classés' END
      ] WHERE f IS NOT NULL] AS faits_marquants
RETURN r.raceId AS course, r.name AS grand_prix, c.name AS circuit, r.date AS date,
       vainqueur.fullName + ' (départ ' + toString(v.grid) + 'e)' AS vainqueur,
       faits_marquants, leader_apres AS leader_du_championnat,
       COLLECT {
         MATCH (r)<-[:IN_RACE]-(x:RaceResult)-[:OF_DRIVER]->(d:Driver),
               (x)-[:FOR_CONSTRUCTOR]->(k:Constructor), (x)-[:WITH_STATUS]->(st:Status)
         WITH x, d, k, st ORDER BY x.position
         RETURN x.positionText + ' ' + d.fullName + ' (' + k.name + ') ' + toString(x.points) + ' pt — ' + st.name
       } AS participants_et_resultats,
       COLLECT {
         MATCH (r)<-[:IN_RACE]-(x:SprintResult)-[:OF_DRIVER]->(d:Driver)
         WITH x, d ORDER BY x.position
         RETURN x.positionText + ' ' + d.fullName + ' ' + toString(x.points) + ' pt'
       } AS sprint
ORDER BY size(faits_marquants) DESC, r.date DESC;


// === Q2 | Which opponents are facing each other again, and what is their head-to-head record?
// Couverture : complète, à une approximation près : l'API ne publie pas la liste
// des engagés d'une course future ; la grille retenue est celle de la saison de
// la prochaine course (ou de la dernière, pendant l'intersaison). Face-à-face =
// courses disputées par les deux ; devant = mieux classé (abandons compris).
// @param a = null
// @param b = null
// --- prérequête : prochaine course au calendrier ; à défaut (intersaison), la
// dernière disputée ; et la saison dont la grille est retenue
OPTIONAL MATCH (p:Race)
WHERE p.date >= date() AND NOT EXISTS { (p)<-[:IN_RACE]-(:RaceResult) }
WITH p ORDER BY p.date LIMIT 1
OPTIONAL MATCH (d:Race) WHERE EXISTS { (d)<-[:IN_RACE]-(:RaceResult) }
WITH p, d ORDER BY d.date DESC LIMIT 1
RETURN coalesce(p.name, d.name) AS course_ref, coalesce(p.date, date()) AS date_ref,
       CASE WHEN p IS NULL THEN d.season ELSE p.season END AS saison_grille;
// --- requête
MATCH (d:Driver)-[:DROVE_FOR {season: $saison_grille}]->(:Constructor)
WITH collect(DISTINCT d) AS grille
UNWIND grille AS a
UNWIND grille AS b
WITH a, b
WHERE a.driverId < b.driverId
  AND ($a IS NULL OR $a IN [a.driverId, b.driverId])
  AND ($b IS NULL OR $b IN [a.driverId, b.driverId])
MATCH (a)<-[:OF_DRIVER]-(ra:RaceResult)-[:IN_RACE]->(r:Race)<-[:IN_RACE]-(rb:RaceResult)-[:OF_DRIVER]->(b)
WHERE r.date < $date_ref
WITH a, b, count(r) AS courses, max(r.date) AS derniere_fois,
     sum(CASE WHEN ra.position < rb.position THEN 1 ELSE 0 END) AS devant_a,
     sum(CASE WHEN rb.position < ra.position THEN 1 ELSE 0 END) AS devant_b
RETURN $course_ref AS prochaine_course, a.fullName AS pilote_a, b.fullName AS pilote_b,
       courses, devant_a, devant_b, derniere_fois
ORDER BY courses DESC, pilote_a
LIMIT 25;


// === Q3 | Which participants are facing a former team or former teammates?
// Couverture : complète. Pour chaque pilote de la grille retenue : ses anciennes
// écuries encore engagées contre lui, et ses anciens coéquipiers désormais dans
// une autre écurie que la sienne.
// --- prérequête : prochaine course au calendrier ; à défaut (intersaison), la
// dernière disputée ; et la saison dont la grille est retenue
OPTIONAL MATCH (p:Race)
WHERE p.date >= date() AND NOT EXISTS { (p)<-[:IN_RACE]-(:RaceResult) }
WITH p ORDER BY p.date LIMIT 1
OPTIONAL MATCH (d:Race) WHERE EXISTS { (d)<-[:IN_RACE]-(:RaceResult) }
WITH p, d ORDER BY d.date DESC LIMIT 1
RETURN coalesce(p.name, d.name) AS course_ref, coalesce(p.date, date()) AS date_ref,
       CASE WHEN p IS NULL THEN d.season ELSE p.season END AS saison_grille;
// --- requête
MATCH (d:Driver)-[:DROVE_FOR {season: $saison_grille}]->(actuelle:Constructor)
WITH d, actuelle,
     COLLECT {
       MATCH (d)-[p:DROVE_FOR]->(k:Constructor)
       WHERE p.season < $saison_grille AND k <> actuelle
         AND EXISTS { (k)<-[:DROVE_FOR {season: $saison_grille}]-(:Driver) }
       RETURN DISTINCT k.name
     } AS anciennes_ecuries_adverses,
     COLLECT {
       MATCH (d)-[p:DROVE_FOR]->(k:Constructor)<-[q:DROVE_FOR]-(t:Driver)
       WHERE p.season = q.season AND p.season < $saison_grille AND t <> d
         AND EXISTS { (t)-[:DROVE_FOR {season: $saison_grille}]->(:Constructor) }
         AND NOT EXISTS { (t)-[:DROVE_FOR {season: $saison_grille}]->(actuelle) }
       RETURN DISTINCT t.fullName
     } AS anciens_coequipiers_adverses
WHERE size(anciennes_ecuries_adverses) > 0 OR size(anciens_coequipiers_adverses) > 0
RETURN $course_ref AS course, d.fullName AS pilote, actuelle.name AS ecurie,
       anciennes_ecuries_adverses, anciens_coequipiers_adverses
ORDER BY pilote;


// === Q4 | Who has moved up or down in the rankings since the previous week?
// Couverture : complète pour la saison en cours. « Semaine précédente » = manche
// précédente. Le classement est recalculé (points de course et de sprint cumulés) :
// l'API ne publie que le classement après la dernière
// manche, rapporté en regard (rang_officiel) pour contrôle. Égalité de points :
// départage au nombre de meilleures places en Grand Prix (victoires, puis
// deuxièmes places…), arrivées classées seulement. Avant 1991, les résultats
// décomptés font diverger ce calcul du classement officiel.
// --- prérequête : dernière saison comptant au moins deux manches disputées
MATCH (r:Race) WHERE EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
WITH r.season AS s, max(r.round) AS manches WHERE manches >= 2
RETURN max(s) AS saison;
// --- requête
MATCH (r:Race {season: $saison})
WHERE EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
WITH max(r.round) AS derniere
UNWIND [derniere - 1, derniere] AS manche
MATCH (d:Driver)<-[:OF_DRIVER]-(x)-[:IN_RACE]->(r:Race {season: $saison})
WHERE (x:RaceResult OR x:SprintResult) AND r.round <= manche
WITH derniere, manche, d, sum(x.points) AS points,
     collect(CASE WHEN x:RaceResult AND x.positionText = toString(x.position) THEN x.position END) AS places
WITH derniere, manche, d, points,
     [i IN range(1, 40) | size([p IN places WHERE p = i])] AS decompte
ORDER BY manche, points DESC, decompte DESC
WITH derniere, manche, collect({pilote: d, points: points}) AS classement
UNWIND range(0, size(classement) - 1) AS i
WITH derniere, manche, classement[i].pilote AS d, i + 1 AS rang, classement[i].points AS points
WITH d, derniere,
     max(CASE WHEN manche = derniere - 1 THEN rang END) AS rang_avant,
     max(CASE WHEN manche = derniere THEN rang END) AS rang_apres,
     max(CASE WHEN manche = derniere THEN points END) AS points
OPTIONAL MATCH (d)-[off:RANKED_IN]->(:Season {year: $saison})
WHERE off.afterRound = derniere
RETURN derniere AS apres_manche, d.fullName AS pilote, rang_avant, rang_apres,
       rang_avant - rang_apres AS places_gagnees, points, off.position AS rang_officiel
ORDER BY rang_apres;


// === Q5 | Which athletes have had the same coach, and during the same period?
// Couverture : PARTIELLE, par substitution. Pas d'entraîneur en F1 ni dans la
// source (voir l'en-tête) : l'encadrement partagé attesté est l'écurie d'une
// saison. Paires de pilotes de la grille retenue ayant eu la même écurie la même
// saison, avec la période commune.
// --- prérequête : dernière saison comptant au moins deux manches disputées
MATCH (r:Race) WHERE EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
WITH r.season AS s, max(r.round) AS manches WHERE manches >= 2
RETURN max(s) AS saison;
// --- requête
MATCH (a:Driver)-[t:TEAMMATE_OF]->(b:Driver)
WHERE EXISTS { (a)-[:DROVE_FOR {season: $saison}]->(:Constructor) }
  AND EXISTS { (b)-[:DROVE_FOR {season: $saison}]->(:Constructor) }
RETURN a.fullName AS pilote_a, b.fullName AS pilote_b, t.constructors AS encadrement_commun,
       t.firstSeason AS de, t.lastSeason AS jusqu_a, t.seasonCount AS saisons
ORDER BY saisons DESC, de
LIMIT 25;


// === Q6 | Which upcoming events involve participants followed by the newsroom?
// Couverture : NON COUVERTE. Le graphe ne sait pas quels pilotes la rédaction
// suit. Il faudrait une source de vérité de la rédaction, par exemple une liste
// de driverId, chargée en (:Journalist)-[:FOLLOWS]->(:Driver).


// === Q7 | Who has performed best against the highest-ranked opponents at the time of the match?
// Couverture : complète. « Les mieux classés au moment du match » = les $top
// premiers au championnat recalculé avant la course (manches précédentes de la
// saison). Duel gagné = arrivée devant l'un d'eux. Première manche exclue (pas
// encore de classement). Un pilote doit compter au moins $duels_min duels.
// @param top = 3
// @param duels_min = 20
// --- prérequête : les cinq dernières saisons disputées
MATCH (r:Race) WHERE EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
WITH max(r.season) AS s
RETURN s - 4 AS de, s AS a;
// --- requête
MATCH (r:Race)
WHERE r.season >= $de AND r.season <= $a AND r.round > 1
  AND EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
CALL (r) {
  MATCH (f:Driver)<-[:OF_DRIVER]-(x)-[:IN_RACE]->(p:Race {season: r.season})
  WHERE (x:RaceResult OR x:SprintResult) AND p.round < r.round
  WITH f, sum(x.points) AS points
  ORDER BY points DESC
  LIMIT $top
  RETURN collect(f) AS favoris
}
MATCH (r)<-[:IN_RACE]-(moi:RaceResult)-[:OF_DRIVER]->(d:Driver)
UNWIND favoris AS f
WITH r, d, moi, f WHERE f <> d
MATCH (r)<-[:IN_RACE]-(lui:RaceResult)-[:OF_DRIVER]->(f)
WITH d, count(*) AS duels, sum(CASE WHEN moi.position < lui.position THEN 1 ELSE 0 END) AS gagnes
WHERE duels >= $duels_min
RETURN d.fullName AS pilote, duels, gagnes, round(100.0 * gagnes / duels, 1) AS pct_gagnes
ORDER BY pct_gagnes DESC, duels DESC
LIMIT 15;


// === Q8 | Which participants are facing a former team or former teammates?
// Doublon de la question 3 : même requête, voir Q3.


// === Q9 | What transfers or coaching changes have been announced, and when do they take effect?
// Couverture : PARTIELLE. Pas de dates d'annonce ni d'encadrement dans la source :
// seuls les changements d'écurie EFFECTIFS sont connus, datés par la première
// course disputée avec la nouvelle écurie (changements en cours de saison compris).
// --- prérequête : dernière saison disputée
MATCH (r:Race) WHERE EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
RETURN max(r.season) AS saison;
// --- requête
MATCH (d:Driver)-[n:DROVE_FOR {season: $saison}]->(nouvelle:Constructor)
WHERE NOT EXISTS { (d)-[:DROVE_FOR {season: $saison - 1}]->(nouvelle) }
WITH d, nouvelle,
     COLLECT { MATCH (d)-[:DROVE_FOR {season: $saison - 1}]->(k:Constructor) RETURN k.name } AS ecuries_saison_precedente,
     COLLECT {
       MATCH (d)<-[:OF_DRIVER]-(x)-[:FOR_CONSTRUCTOR]->(nouvelle), (x)-[:IN_RACE]->(r:Race {season: $saison})
       WHERE x:RaceResult OR x:QualifyingResult OR x:SprintResult
       RETURN r ORDER BY r.date LIMIT 1
     } AS premiere
RETURN d.fullName AS pilote, ecuries_saison_precedente AS depuis, nouvelle.name AS vers,
       premiere[0].name AS effectif_au_grand_prix, premiere[0].date AS effectif_le,
       CASE WHEN size(ecuries_saison_precedente) = 0 THEN 'absent la saison précédente' END AS remarque
ORDER BY effectif_le, pilote;


// === Q10 | If a coach is removed from the network, which players or groups become disconnected?
// Couverture : PARTIELLE, par analogie. Sans entraîneur, l'équivalent mesurable est
// l'écurie : la retirer coupe les pilotes qui n'ont couru que pour elle du reste du
// réseau des coéquipiers, et défait les binômes qu'elle seule réunissait.
// --- prérequête : l'écurie dont le retrait isole le plus de pilotes
MATCH (d:Driver)-[:DROVE_FOR]->(k:Constructor)
WITH d, collect(DISTINCT k) AS ecuries WHERE size(ecuries) = 1
WITH ecuries[0] AS k, count(d) AS isoles ORDER BY isoles DESC LIMIT 1
RETURN k.constructorId AS ecurie;
// --- requête
MATCH (k:Constructor {constructorId: $ecurie})
RETURN k.name AS ecurie,
       COLLECT {
         MATCH (d:Driver)-[:DROVE_FOR]->(k)
         WHERE NOT EXISTS { (d)-[:DROVE_FOR]->(autre:Constructor) WHERE autre <> k }
         RETURN DISTINCT d.fullName
       } AS pilotes_isoles,
       COUNT {
         MATCH (a:Driver)-[p:DROVE_FOR]->(k)<-[q:DROVE_FOR]-(b:Driver)
         WHERE p.season = q.season AND a.driverId < b.driverId
           AND NOT EXISTS {
             MATCH (a)-[p2:DROVE_FOR]->(k2:Constructor)<-[q2:DROVE_FOR]-(b)
             WHERE k2 <> k AND p2.season = q2.season
           }
         RETURN DISTINCT a, b
       } AS binomes_defaits;


// === Q11 | Which players are indirectly connected through their career paths, without having attended the same academy or shared a coach?
// Couverture : PARTIELLE. Ni académie ni entraîneur dans la source : la condition
// d'exclusion ne peut pas être vérifiée. Restent les pilotes reliés par un
// coéquipier commun sans avoir jamais été coéquipiers eux-mêmes, avec les
// intermédiaires, par la relation dérivée TEAMMATE_OF.
// --- prérequête : le pilote de la dernière grille au réseau de coéquipiers le plus riche
MATCH (r:Race) WHERE EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
WITH max(r.season) AS s
MATCH (d:Driver)-[:DROVE_FOR {season: s}]->(:Constructor)
WITH DISTINCT d
WITH d, size(COLLECT { MATCH (d)-[p:DROVE_FOR]->(:Constructor)<-[q:DROVE_FOR]-(t:Driver)
                       WHERE p.season = q.season AND t <> d RETURN DISTINCT t }) AS coequipiers
ORDER BY coequipiers DESC LIMIT 1
RETURN d.driverId AS pilote;
// --- requête
MATCH (a:Driver {driverId: $pilote})-[:TEAMMATE_OF]-(m:Driver)-[:TEAMMATE_OF]-(b:Driver)
WHERE b <> a AND NOT EXISTS { (a)-[:TEAMMATE_OF]-(b) }
WITH b, collect(DISTINCT m.fullName) AS par_l_intermediaire_de
RETURN b.fullName AS pilote_relie, size(par_l_intermediaire_de) AS intermediaires, par_l_intermediaire_de
ORDER BY intermediaires DESC, pilote_relie
LIMIT 25;


// === Q12 | Which coaches connect players from different academies?
// Couverture : NON COUVERTE. Même en remplaçant l'entraîneur par l'écurie, il
// faudrait les académies de pilotes : absentes de la source, et quasi vides dans
// Wikidata (deux membres recensés pour la Red Bull Junior Team, le 17 octobre 2026).


// === Q13 | Which teams are connected by multiple independent paths, such as a coach, sponsor, executive, or former teammate?
// Couverture : PARTIELLE. Seul un type de chemin existe dans les données : le
// pilote passé par les deux écuries. Pas de sponsors, dirigeants ni entraîneurs.
// Chemins indépendants = pilotes distincts.
// @param chemins_min = 4
MATCH (k1:Constructor)<-[:DROVE_FOR]-(d:Driver)-[:DROVE_FOR]->(k2:Constructor)
WHERE k1.constructorId < k2.constructorId
WITH k1, k2, collect(DISTINCT d.fullName) AS pilotes
WHERE size(pilotes) >= $chemins_min
RETURN k1.name AS ecurie_1, k2.name AS ecurie_2, size(pilotes) AS chemins_independants, pilotes
ORDER BY chemins_independants DESC
LIMIT 20;


// === Q14 | What documented links connect federation decision-makers, the executives of the teams involved, and their sponsors, either directly or through no more than three intermediaries?
// Couverture : NON COUVERTE. Ni fédération, ni dirigeants, ni sponsors dans la source.


// === Q15 | Do the champions of the past ten years belong to shared training and coaching networks, even if they never directly shared an organization?
// Couverture : PARTIELLE. Pas de réseaux de formation ni d'encadrement : la
// requête mesure leur proximité dans le réseau des coéquipiers (plus courte chaîne),
// et dit s'ils ont partagé une écurie, même à des saisons différentes.
// @param saisons = 10
// --- requête
MATCH (c:Driver)-[k:RANKED_IN]->(s:Season)
WHERE k.position = 1 AND s.year < date().year AND s.year >= date().year - $saisons
WITH collect(DISTINCT c) AS champions
UNWIND champions AS a
UNWIND champions AS b
WITH a, b WHERE a.driverId < b.driverId
OPTIONAL MATCH ch = shortestPath((a)-[:TEAMMATE_OF*..10]-(b))
RETURN a.fullName AS champion_a, b.fullName AS champion_b,
       EXISTS { (a)-[:DROVE_FOR]->(:Constructor)<-[:DROVE_FOR]-(b) } AS meme_ecurie_un_jour,
       length(ch) - 1 AS intermediaires,
       [n IN nodes(ch) | n.fullName] AS chaine_de_coequipiers
ORDER BY intermediaires, champion_a;


// === Q16 | Do the two opponents have a shared history, such as a team, coach, training center, or mutual teammates? What indirect connections link them?
// Couverture : PARTIELLE. Écuries communes, saisons comme coéquipiers, coéquipiers
// communs, et plus courte chaîne de coéquipiers. Pas d'entraîneurs ni de centres
// de formation dans la source.
// --- prérequête : les deux premiers du dernier classement des pilotes (rivaux pour le titre)
MATCH (:Driver)-[:RANKED_IN]->(s:Season)
WITH max(s.year) AS annee
MATCH (d:Driver)-[k:RANKED_IN]->(:Season {year: annee})
WHERE k.position IN [1, 2]
WITH d, k ORDER BY k.position
WITH collect(d.driverId) AS duo
RETURN duo[0] AS a, duo[1] AS b;
// --- requête
MATCH (a:Driver {driverId: $a}), (b:Driver {driverId: $b})
OPTIONAL MATCH ch = shortestPath((a)-[:TEAMMATE_OF*..10]-(b))
RETURN a.fullName AS pilote_a, b.fullName AS pilote_b,
       COLLECT { MATCH (a)-[t:TEAMMATE_OF]-(b) UNWIND t.seasons AS saison RETURN saison } AS coequipiers_en,
       COLLECT { MATCH (a)-[:DROVE_FOR]->(k:Constructor)<-[:DROVE_FOR]-(b) RETURN DISTINCT k.name } AS ecuries_communes,
       COLLECT { MATCH (a)-[:TEAMMATE_OF]-(t:Driver)-[:TEAMMATE_OF]-(b) RETURN DISTINCT t.fullName } AS coequipiers_communs,
       [n IN nodes(ch) | n.fullName] AS chaine_de_coequipiers;



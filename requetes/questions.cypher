// =============================================================================
//  Graphe F1 — questions de la rédaction
// =============================================================================
//
//  Transposition F1 des questions : événement = Grand Prix, participants et
//  adversaires = pilotes, équipe = écurie (Constructor), coéquipiers = pilotes
//  d'une même écurie LA MÊME SAISON (relation dérivée TEAMMATE_OF).
//
//  Sources : résultats de l'API Jolpica-F1 ; académies de pilotes lues dans
//  Wikipédia (Academy, MEMBER_OF, FEEDS, voir complements.py) ; pilotes et
//  écuries suivis par la rédaction (referentiel/suivis.csv, tenu par elle).
//  Toujours absents, faute de source publique structurée : directeurs d'équipe,
//  ingénieurs, sponsors, dirigeants, fédération, dates d'annonce.
//
//  « Entraîneur » n'existe pas en F1. Deux équivalents sont attestés par les
//  données, et chaque question dit lequel elle retient :
//    l'ACADÉMIE de pilotes (programme de formation d'une écurie : Red Bull Junior
//      Team, Ferrari Driver Academy…), pour la formation, avant et pendant la F1 ;
//    l'ÉCURIE D'UNE SAISON (mêmes ingénieurs, même direction), pour l'encadrement
//      en course.
//
//  Couverture : complète / partielle (ce qui manque est dit) / non couverte.
//
//  Structure de chaque bloc, dans cet ordre :
//    « @param nom = expression »  valeur fixe par défaut (expression Cypher) ;
//    « @etape titre | motif | filtres »  explication pas à pas de la requête :
//                                 ce qu'elle parcourt, et les filtres (WHERE,
//                                 LIMIT…) appliqués à chaque étape ;
//    « // --- prérequête »        requête qui CHERCHE dans la base des valeurs pour
//                                 lesquelles la question a une réponse ; ses
//                                 colonnes deviennent des paramètres ;
//    « // --- requête »           la requête qui répond à la question.
//  questions.py enchaîne le tout et affiche chaque requête exécutée ; --param
//  surcharge n'importe quel paramètre :
//      python questions.py 16 --param a="'alonso'" --param b="'hamilton'"
//
//  Syntaxe : Cypher 5, Neo4j >= 5.23 (CALL (x) { … }, COLLECT { … }).
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
// @etape Fenêtre de temps | (prérequête) Race | date ≤ aujourd'hui ET au moins un RaceResult ; dernier = max(date) ; début = dernier − $semaines semaines
// @etape Grands Prix de la fenêtre | (Race)-[:HELD_AT]->(Circuit) | $debut ≤ date ≤ $fin ET course disputée (EXISTS RaceResult)
// @etape Vainqueur | (Race)<-[:IN_RACE]-(RaceResult)-[:OF_DRIVER]->(Driver) | position = 1
// @etape Leader avant et après | sous-requête : (Driver)<-[:OF_DRIVER]-(résultat)-[:IN_RACE]->(Race de la même saison) | RaceResult OU SprintResult ; manche ≤ manche courante ; somme des points, tri décroissant, premier
// @etape Faits marquants | vainqueur, grille, abandons | aucune victoire antérieure du vainqueur ; grille ≥ $depart_lointain ; leader avant ≠ leader après ; non classés ≥ $abandons_nombreux
// @etape Participants et classement | (Race)<-[:IN_RACE]-(RaceResult)-[:OF_DRIVER, FOR_CONSTRUCTOR, WITH_STATUS] | tri par position ; puis Grands Prix triés par nombre de faits, puis date décroissante
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
// @etape Course de référence | (prérequête) Race | prochaine course : date ≥ aujourd'hui SANS résultat, tri par date, LIMIT 1 ; à défaut la dernière disputée
// @etape Grille | (Driver)-[:DROVE_FOR]->(Constructor) | DROVE_FOR.season = $saison_grille
// @etape Paires d'adversaires | grille × grille | a.driverId < b.driverId (chaque paire une fois) ; $a, $b s'ils sont donnés
// @etape Courses communes | (a)<-[:OF_DRIVER]-(RaceResult)-[:IN_RACE]->(Race)<-[:IN_RACE]-(RaceResult)-[:OF_DRIVER]->(b) | date de la course < $date_ref
// @etape Bilan | comptage par paire | devant = position inférieure ; tri par nombre de courses communes ; LIMIT 25
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
// @etape Course de référence | (prérequête) Race | comme Q2 : prochaine course, à défaut la dernière disputée
// @etape Pilote et écurie actuelle | (Driver)-[:DROVE_FOR]->(Constructor) | DROVE_FOR.season = $saison_grille
// @etape Anciennes écuries adverses | (Driver)-[:DROVE_FOR]->(Constructor) | saison < $saison_grille ; écurie ≠ actuelle ; écurie engagée cette saison (EXISTS DROVE_FOR $saison_grille)
// @etape Anciens coéquipiers adverses | (Driver)-[:DROVE_FOR]->(Constructor)<-[:DROVE_FOR]-(Driver) | même saison ; saison < $saison_grille ; coéquipier engagé cette saison ; PAS dans l'écurie actuelle
// @etape Résultat | une ligne par pilote | au moins une ancienne écurie OU un ancien coéquipier adverse
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
// l'API ne publie que le classement après la dernière manche, rapporté en regard
// (rang_officiel) pour contrôle. Égalité de points : départage au nombre de
// meilleures places en Grand Prix (victoires, puis deuxièmes places…), arrivées
// classées seulement. Avant 1991, les résultats décomptés font diverger ce calcul.
// @etape Saison | (prérequête) Race | course disputée ; saisons d'au moins 2 manches ; la plus récente
// @etape Deux manches comparées | Race de la saison | dernière manche disputée, et la précédente
// @etape Points cumulés | (Driver)<-[:OF_DRIVER]-(résultat)-[:IN_RACE]->(Race) | RaceResult OU SprintResult ; manche ≤ manche comparée
// @etape Classement | tri | points décroissants, puis nombre de victoires, de 2es places… (positions classées seulement)
// @etape Évolution | rang avant − rang après | rang officiel lu dans RANKED_IN si afterRound = dernière manche
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
// Couverture : complète, par substitution. « Même entraîneur » = même ACADÉMIE de
// pilotes (Wikipédia) ; « même période » = années d'adhésion qui se chevauchent.
// Une adhésion en cours compte jusqu'à l'année courante. Les coéquipiers (même
// écurie, même saison) sont l'autre équivalent : relation TEAMMATE_OF, question 16.
// @etape Adhésions | (Driver)-[:MEMBER_OF]->(Academy)<-[:MEMBER_OF]-(Driver) | a.driverId < b.driverId (chaque paire une fois)
// @etape Période commune | années de début et de fin | début commun = max(débuts) ; fin commune = min(fins, en cours = année courante) ; début commun ≤ fin commune
// @etape Résultat | une ligne par paire et académie | tri par durée commune décroissante ; LIMIT 30
// --- requête
MATCH (a:Driver)-[m1:MEMBER_OF]->(ac:Academy)<-[m2:MEMBER_OF]-(b:Driver)
WHERE a.driverId < b.driverId
WITH a, b, ac,
     CASE WHEN m1.fromYear > m2.fromYear THEN m1.fromYear ELSE m2.fromYear END AS debut,
     CASE WHEN coalesce(m1.toYear, date().year) < coalesce(m2.toYear, date().year)
          THEN coalesce(m1.toYear, date().year) ELSE coalesce(m2.toYear, date().year) END AS fin
WHERE debut <= fin
RETURN a.fullName AS pilote_a, b.fullName AS pilote_b, ac.name AS academie,
       debut AS ensemble_de, fin AS ensemble_jusqu_a, fin - debut + 1 AS annees_communes
ORDER BY annees_communes DESC, ensemble_de
LIMIT 30;


// === Q6 | Which upcoming events involve participants followed by the newsroom?
// Couverture : complète, dès que la rédaction renseigne referentiel/suivis.csv
// (pilotes ou écuries qu'elle suit). Sans suivi déclaré, la réponse est vide : rien
// n'est deviné. Engagés d'une course future = pilotes et écuries de sa saison,
// l'API ne publiant pas la liste des engagés.
// @param prochaines = 3
// @etape Suivis | (prérequête) (Newsroom)-[:FOLLOWS]->(Driver ou Constructor) | comptage : 0 = referentiel/suivis.csv vide
// @etape Prochaines courses | Race | date ≥ aujourd'hui ET aucun résultat ; tri par date ; LIMIT $prochaines
// @etape Suivis engagés | (Newsroom)-[:FOLLOWS]->(x) | pilote : DROVE_FOR de la saison de la course ; écurie : au moins un pilote engagé cette saison
// @etape Résultat | une ligne par course | au moins un suivi engagé ; tri par date
// --- prérequête : nombre de suivis déclarés par la rédaction
OPTIONAL MATCH (:Newsroom)-[f:FOLLOWS]->()
RETURN count(f) AS suivis_declares;
// --- requête
MATCH (r:Race)
WHERE r.date >= date() AND NOT EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
WITH r ORDER BY r.date LIMIT $prochaines
MATCH (:Newsroom)-[:FOLLOWS]->(x)
WHERE (x:Driver AND EXISTS { (x)-[:DROVE_FOR {season: r.season}]->(:Constructor) })
   OR (x:Constructor AND EXISTS { (x)<-[:DROVE_FOR {season: r.season}]-(:Driver) })
RETURN r.name AS grand_prix, r.date AS date,
       [n IN collect(x) WHERE n:Driver | n.fullName] AS pilotes_suivis,
       [n IN collect(x) WHERE n:Constructor | n.name] AS ecuries_suivies
ORDER BY date;


// === Q7 | Who has performed best against the highest-ranked opponents at the time of the match?
// Couverture : complète. « Les mieux classés au moment du match » = les $top
// premiers au championnat recalculé avant la course (manches précédentes de la
// saison). Duel gagné = arrivée devant l'un d'eux. Première manche exclue (pas
// encore de classement). Un pilote doit compter au moins $duels_min duels.
// @param top = 3
// @param duels_min = 20
// @etape Période | (prérequête) Race | les cinq dernières saisons disputées
// @etape Courses | Race | $de ≤ saison ≤ $a ; manche > 1 ; course disputée
// @etape Favoris au départ | sous-requête : points cumulés AVANT la course | manches < manche courante ; tri décroissant ; LIMIT $top
// @etape Duels | (Race)<-[:IN_RACE]-(RaceResult)-[:OF_DRIVER]->(Driver) × favoris | favori ≠ pilote lui-même ; duel gagné = position < position du favori
// @etape Résultat | par pilote | duels ≥ $duels_min ; tri par % de duels gagnés ; LIMIT 15
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
// Couverture : PARTIELLE. Pas de dates d'annonce dans les sources : seuls les
// changements EFFECTIFS sont connus. Transferts : nouvelle écurie, datée par la
// première course disputée avec elle. Changements d'encadrement : entrées dans une
// académie l'année $saison et sorties à la fin de l'année précédente (Wikipédia,
// à l'année près).
// @etape Saison | (prérequête) Race | dernière saison disputée
// @etape Transferts | (Driver)-[:DROVE_FOR]->(Constructor) | DROVE_FOR.season = $saison ET pas de DROVE_FOR vers cette écurie en $saison − 1
// @etape Date d'effet du transfert | (Driver)<-[:OF_DRIVER]-(résultat)-[:FOR_CONSTRUCTOR]->(nouvelle écurie) | course de $saison ; tri par date ; LIMIT 1
// @etape Entrées en académie | (Driver)-[:MEMBER_OF]->(Academy) | fromYear = $saison
// @etape Sorties d'académie | (Driver)-[:MEMBER_OF]->(Academy) | toYear = $saison − 1
// @etape Résultat | UNION ALL des trois listes | tri par date d'effet
// --- prérequête : dernière saison disputée
MATCH (r:Race) WHERE EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
RETURN max(r.season) AS saison;
// --- requête
MATCH (d:Driver)-[:DROVE_FOR {season: $saison}]->(nouvelle:Constructor)
WHERE NOT EXISTS { (d)-[:DROVE_FOR {season: $saison - 1}]->(nouvelle) }
WITH d, nouvelle,
     COLLECT { MATCH (d)-[:DROVE_FOR {season: $saison - 1}]->(k:Constructor) RETURN k.name } AS avant,
     COLLECT {
       MATCH (d)<-[:OF_DRIVER]-(x)-[:FOR_CONSTRUCTOR]->(nouvelle), (x)-[:IN_RACE]->(r:Race {season: $saison})
       WHERE x:RaceResult OR x:QualifyingResult OR x:SprintResult
       RETURN r ORDER BY r.date LIMIT 1
     } AS premiere
RETURN 'transfert' AS changement, d.fullName AS pilote,
       CASE WHEN size(avant) = 0 THEN 'absent en ' + toString($saison - 1)
            ELSE reduce(t = '', n IN avant | t + CASE WHEN t = '' THEN '' ELSE ', ' END + n) END AS depuis,
       nouvelle.name AS vers, toString(premiere[0].date) + ' (' + premiere[0].name + ')' AS effectif
UNION ALL
MATCH (d:Driver)-[m:MEMBER_OF]->(ac:Academy)
WHERE m.fromYear = $saison
RETURN 'entrée en académie' AS changement, d.fullName AS pilote, '—' AS depuis, ac.name AS vers,
       toString($saison) AS effectif
UNION ALL
MATCH (d:Driver)-[m:MEMBER_OF]->(ac:Academy)
WHERE m.toYear = $saison - 1
RETURN 'sortie d''académie' AS changement, d.fullName AS pilote, ac.name AS depuis, '—' AS vers,
        'fin ' + toString($saison - 1) AS effectif;


// === Q10 | If a coach is removed from the network, which players or groups become disconnected?
// Couverture : PARTIELLE, par analogie. L'encadrement retenu est l'ÉCURIE : la
// retirer coupe du réseau des coéquipiers les pilotes qui n'ont couru que pour
// elle, et défait les binômes qu'elle seule réunissait. Les académies ne relient pas
// les pilotes entre eux dans ce réseau : les retirer n'isolerait personne.
// @etape Écurie retirée | (prérequête) (Driver)-[:DROVE_FOR]->(Constructor) | pilotes n'ayant couru que pour UNE écurie ; l'écurie qui en compte le plus
// @etape Pilotes isolés | (Driver)-[:DROVE_FOR]->(écurie) | AUCUN DROVE_FOR vers une autre écurie
// @etape Binômes défaits | (a)-[:DROVE_FOR]->(écurie)<-[:DROVE_FOR]-(b) | même saison ; a.driverId < b.driverId ; jamais coéquipiers dans une autre écurie
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
// Couverture : complète, par substitution. Reliés indirectement = un coéquipier
// commun (TEAMMATE_OF à deux pas). Exclus : les pilotes déjà coéquipiers (même
// encadrement d'écurie) et ceux passés par une même académie, à n'importe quelle
// époque.
// @etape Pilote de départ | (prérequête) (Driver)-[:DROVE_FOR]->(Constructor) | grille de la dernière saison ; le plus de coéquipiers distincts
// @etape Deux pas de coéquipiers | (a)-[:TEAMMATE_OF]-(m)-[:TEAMMATE_OF]-(b) | b ≠ a
// @etape Pas d'encadrement commun | NOT EXISTS (a)-[:TEAMMATE_OF]-(b) | jamais coéquipiers
// @etape Pas d'académie commune | NOT EXISTS (a)-[:MEMBER_OF]->(Academy)<-[:MEMBER_OF]-(b) | aucune académie en commun
// @etape Résultat | par pilote relié | intermédiaires collectés ; tri par nombre d'intermédiaires ; LIMIT 25
// --- prérequête : le pilote de la dernière grille au réseau de coéquipiers le plus riche
MATCH (r:Race) WHERE EXISTS { (r)<-[:IN_RACE]-(:RaceResult) }
WITH max(r.season) AS s
MATCH (d:Driver)-[:DROVE_FOR {season: s}]->(:Constructor)
WITH DISTINCT d
WITH d, COUNT { (d)-[:TEAMMATE_OF]-(:Driver) } AS coequipiers
ORDER BY coequipiers DESC LIMIT 1
RETURN d.driverId AS pilote;
// --- requête
MATCH (a:Driver {driverId: $pilote})-[:TEAMMATE_OF]-(m:Driver)-[:TEAMMATE_OF]-(b:Driver)
WHERE b <> a
  AND NOT EXISTS { (a)-[:TEAMMATE_OF]-(b) }
  AND NOT EXISTS { (a)-[:MEMBER_OF]->(:Academy)<-[:MEMBER_OF]-(b) }
WITH b, collect(DISTINCT m.fullName) AS par_l_intermediaire_de
RETURN b.fullName AS pilote_relie, size(par_l_intermediaire_de) AS intermediaires, par_l_intermediaire_de
ORDER BY intermediaires DESC, pilote_relie
LIMIT 25;


// === Q12 | Which coaches connect players from different academies?
// Couverture : complète, par substitution. « Entraîneur » = encadrement de course :
// l'ÉCURIE D'UNE SAISON. Elle relie des académies quand elle fait courir, la même
// saison, des pilotes formés dans des académies différentes (adhésion commencée
// avant ou pendant cette saison).
// @etape Pilotes engagés | (Driver)-[:DROVE_FOR]->(Constructor) | toutes saisons
// @etape Formation | (Driver)-[:MEMBER_OF]->(Academy) | année d'entrée ≤ saison de l'engagement
// @etape Écurie-saison | regroupement par écurie et saison | au moins 2 académies DIFFÉRENTES
// @etape Résultat | une ligne par écurie-saison | tri par nombre d'académies, puis saison décroissante ; LIMIT 25
// --- requête
MATCH (d:Driver)-[f:DROVE_FOR]->(k:Constructor)
MATCH (d)-[m:MEMBER_OF]->(ac:Academy)
WHERE m.fromYear <= f.season
WITH k, f.season AS saison, collect(DISTINCT ac.name) AS academies,
     collect(DISTINCT d.fullName + ' (' + ac.name + ')') AS pilotes
WHERE size(academies) >= 2
RETURN k.name AS encadrement, saison, size(academies) AS nb_academies, academies, pilotes
ORDER BY nb_academies DESC, saison DESC
LIMIT 25;


// === Q13 | Which teams are connected by multiple independent paths, such as a coach, sponsor, executive, or former teammate?
// Couverture : PARTIELLE. Deux types de chemins existent dans les données : le
// PILOTE passé par les deux écuries, et l'ACADÉMIE qui alimente l'une et a formé
// un pilote de l'autre. Pas de sponsors ni de dirigeants dans les sources.
// Chemins indépendants = intermédiaires distincts ; types = nature des chemins.
// @param chemins_min = 4
// @etape Chemins par pilote | (k1)<-[:DROVE_FOR]-(Driver)-[:DROVE_FOR]->(k2) | k1 < k2 (chaque paire une fois)
// @etape Chemins par académie | (k1)<-[:FEEDS]-(Academy)<-[:MEMBER_OF]-(Driver)-[:DROVE_FOR]->(k2) | k1 ≠ k2 ; paire remise en ordre k1 < k2
// @etape Regroupement | par paire d'écuries | intermédiaires distincts par type
// @etape Résultat | une ligne par paire | total ≥ $chemins_min ; tri par nombre de types, puis total ; LIMIT 20
// --- requête
CALL () {
  MATCH (k1:Constructor)<-[:DROVE_FOR]-(d:Driver)-[:DROVE_FOR]->(k2:Constructor)
  WHERE k1.constructorId < k2.constructorId
  RETURN k1, k2, 'pilote' AS type, d.fullName AS intermediaire
  UNION
  MATCH (ka:Constructor)<-[:FEEDS]-(ac:Academy)<-[:MEMBER_OF]-(d:Driver)-[:DROVE_FOR]->(kb:Constructor)
  WHERE ka <> kb
  RETURN CASE WHEN ka.constructorId < kb.constructorId THEN ka ELSE kb END AS k1,
         CASE WHEN ka.constructorId < kb.constructorId THEN kb ELSE ka END AS k2,
         'académie' AS type, ac.name AS intermediaire
}
WITH k1, k2, type, collect(DISTINCT intermediaire) AS intermediaires
WITH k1, k2, collect({type: type, n: size(intermediaires), via: intermediaires}) AS chemins,
     sum(size(intermediaires)) AS total
WHERE total >= $chemins_min
RETURN k1.name AS ecurie_1, k2.name AS ecurie_2, size(chemins) AS types_de_chemins, total AS chemins_independants,
       [c IN chemins | c.type + ' : ' + toString(c.n)] AS detail,
       reduce(v = [], c IN chemins | v + c.via) AS intermediaires
ORDER BY types_de_chemins DESC, chemins_independants DESC
LIMIT 20;


// === Q14 | What documented links connect federation decision-makers, the executives of the teams involved, and their sponsors, either directly or through no more than three intermediaries?
// Couverture : NON COUVERTE. Ni décideurs de la fédération (président de la FIA,
// directeur de course, commissaires), ni dirigeants d'écurie, ni sponsors dans des
// sources publiques structurées. Pistes : documents officiels de la FIA (décisions
// des commissaires, nominatifs), article Wikipédia « Formula One sponsorship
// liveries » (sponsors par écurie et par saison, tableaux hétérogènes).


// === Q15 | Do the champions of the past ten years belong to shared training and coaching networks, even if they never directly shared an organization?
// Couverture : complète, par substitution. Réseau de formation = académies
// (MEMBER_OF) ; réseau d'encadrement = coéquipiers (TEAMMATE_OF). Pour chaque paire
// de champions : académies de chacun, académie commune, organisation commune
// (écurie ou académie), et plus courte chaîne dans le réseau mêlant les deux.
// @param saisons = 10
// @etape Champions | (Driver)-[:RANKED_IN]->(Season) | position = 1 ; année < année courante ; année ≥ année courante − $saisons
// @etape Paires | champions × champions | a.driverId < b.driverId
// @etape Académies | (Driver)-[:MEMBER_OF]->(Academy) | pour chacun des deux
// @etape Organisation commune | EXISTS écurie commune OU académie commune | à n'importe quelle époque
// @etape Réseau commun | shortestPath((a)-[:TEAMMATE_OF|MEMBER_OF*..10]-(b)) | chemin non orienté, au plus 10 relations, passant par des pilotes ou des académies
// --- requête
MATCH (c:Driver)-[k:RANKED_IN]->(s:Season)
WHERE k.position = 1 AND s.year < date().year AND s.year >= date().year - $saisons
WITH collect(DISTINCT c) AS champions
UNWIND champions AS a
UNWIND champions AS b
WITH a, b WHERE a.driverId < b.driverId
OPTIONAL MATCH ch = shortestPath((a)-[:TEAMMATE_OF|MEMBER_OF*..10]-(b))
RETURN a.fullName AS champion_a, b.fullName AS champion_b,
       COLLECT { MATCH (a)-[:MEMBER_OF]->(x:Academy) RETURN DISTINCT x.name } AS academies_a,
       COLLECT { MATCH (b)-[:MEMBER_OF]->(x:Academy) RETURN DISTINCT x.name } AS academies_b,
       EXISTS { (a)-[:DROVE_FOR]->(:Constructor)<-[:DROVE_FOR]-(b) }
         OR EXISTS { (a)-[:MEMBER_OF]->(:Academy)<-[:MEMBER_OF]-(b) } AS organisation_commune,
       length(ch) AS longueur_chaine,
       [n IN nodes(ch) | coalesce(n.fullName, n.name)] AS chaine
ORDER BY longueur_chaine, champion_a;


// === Q16 | Do the two opponents have a shared history, such as a team, coach, training center, or mutual teammates? What indirect connections link them?
// Couverture : complète, par substitution. Écuries communes, saisons comme
// coéquipiers (encadrement partagé), académies communes (centre de formation),
// coéquipiers communs, et plus courte chaîne dans le réseau des coéquipiers et des
// académies.
// @etape Rivaux | (prérequête) (Driver)-[:RANKED_IN]->(Season) | dernière saison classée ; positions 1 et 2
// @etape Coéquipiers | (a)-[:TEAMMATE_OF]-(b) | saisons partagées
// @etape Écuries communes | (a)-[:DROVE_FOR]->(Constructor)<-[:DROVE_FOR]-(b) | à n'importe quelle saison
// @etape Académies communes | (a)-[:MEMBER_OF]->(Academy)<-[:MEMBER_OF]-(b) | avec les années de chacun
// @etape Coéquipiers communs | (a)-[:TEAMMATE_OF]-(Driver)-[:TEAMMATE_OF]-(b) | intermédiaire distinct des deux
// @etape Chaîne indirecte | shortestPath((a)-[:TEAMMATE_OF|MEMBER_OF*..10]-(b)) | non orientée, au plus 10 relations
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
OPTIONAL MATCH ch = shortestPath((a)-[:TEAMMATE_OF|MEMBER_OF*..10]-(b))
RETURN a.fullName AS pilote_a, b.fullName AS pilote_b,
       COLLECT { MATCH (a)-[t:TEAMMATE_OF]-(b) UNWIND t.seasons AS saison RETURN saison } AS coequipiers_en,
       COLLECT { MATCH (a)-[:DROVE_FOR]->(k:Constructor)<-[:DROVE_FOR]-(b) RETURN DISTINCT k.name } AS ecuries_communes,
       COLLECT {
         MATCH (a)-[ma:MEMBER_OF]->(ac:Academy)<-[mb:MEMBER_OF]-(b)
         RETURN ac.name + ' (' + toString(ma.fromYear) + '–' + coalesce(toString(ma.toYear), '') + ' / '
                + toString(mb.fromYear) + '–' + coalesce(toString(mb.toYear), '') + ')'
       } AS academies_communes,
       COLLECT { MATCH (a)-[:TEAMMATE_OF]-(t:Driver)-[:TEAMMATE_OF]-(b) RETURN DISTINCT t.fullName } AS coequipiers_communs,
       [n IN nodes(ch) | coalesce(n.fullName, n.name)] AS chaine;

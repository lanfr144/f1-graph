// =============================================================================
//  Graphe F1 — requêtes de référence
// =============================================================================
//
//  Chaque requête justifie un index de 03_index.cypher. Préfixer par PROFILE
//  pour vérifier que l'opérateur NodeIndexSeek / NodeIndexScan /
//  DirectedRelationshipIndexSeek (et non NodeByLabelScan) est bien utilisé.
//
//  Ce fichier n'est pas exécuté par charger.py : il documente.
// -----------------------------------------------------------------------------

// R1 — race_date : les Grands Prix d'une décennie.
MATCH (r:Race)
WHERE r.date >= date('1980-01-01') AND r.date < date('1990-01-01')
RETURN r.raceId, r.name, r.date
ORDER BY r.date;

// R2 — race_season : calendrier d'une saison.
MATCH (r:Race)-[:HELD_AT]->(c:Circuit)
WHERE r.season = 2024
RETURN r.round, r.name, c.name, r.startsAt
ORDER BY r.round;

// R3 — race_result_position : les pilotes les plus victorieux.
MATCH (res:RaceResult)-[:OF_DRIVER]->(d:Driver)
WHERE res.position = 1
RETURN d.fullName, count(*) AS victoires
ORDER BY victoires DESC
LIMIT 10;

// R4 — ranked_in_position : palmarès des champions du monde pilotes.
MATCH (d:Driver)-[k:RANKED_IN]->(s:Season)
WHERE k.position = 1
RETURN s.year, d.fullName, k.points
ORDER BY s.year;

// R5 — pit_stop_duration : les dix arrêts les plus courts.
MATCH (p:PitStop)
WHERE p.durationMillis IS NOT NULL
RETURN p.pitStopId, p.duration
ORDER BY p.durationMillis
LIMIT 10;

// R6 — circuit_location : circuits à moins de 500 km du Luxembourg.
WITH point({latitude: 49.6116, longitude: 6.1319}) AS lux
MATCH (c:Circuit)
WHERE point.distance(c.location, lux) < 500000
RETURN c.name, round(point.distance(c.location, lux) / 1000) AS km
ORDER BY km;

// R7 — driver_name_search : « raikkonen » trouve Räikkönen.
CALL db.index.fulltext.queryNodes('driver_name_search', 'raikkonen')
YIELD node, score
RETURN node.fullName, node.driverId, score;

// R8 — constructor_name_search.
CALL db.index.fulltext.queryNodes('constructor_name_search', 'red bull')
YIELD node, score
RETURN node.name, node.constructorId, score;

// R9 — circuit_name_search : recherche floue (~) sur le nom ou la localité.
CALL db.index.fulltext.queryNodes('circuit_name_search', 'monaco~')
YIELD node, score
RETURN node.name, node.locality, score;

// --- Requêtes de graphe (sans index dédié : elles partent d'une clé) ---------

// Coéquipiers d'un pilote, saison par saison.
MATCH (d:Driver {driverId: 'alonso'})-[f:DROVE_FOR]->(k:Constructor)<-[g:DROVE_FOR]-(t:Driver)
WHERE f.season = g.season AND t <> d
RETURN f.season, k.name, collect(t.fullName) AS coequipiers
ORDER BY f.season;

// Parcours d'un pilote d'écurie en écurie.
MATCH (d:Driver {driverId: 'hamilton'})-[f:DROVE_FOR]->(k:Constructor)
RETURN k.name, min(f.season) AS de, max(f.season) AS a
ORDER BY de;

// Grille contre arrivée sur une course.
MATCH (r:Race {raceId: '2024-01'})<-[:IN_RACE]-(res:RaceResult)-[:OF_DRIVER]->(d:Driver),
      (res)-[:WITH_STATUS]->(st:Status)
RETURN res.positionText, d.code, res.grid, res.grid - res.position AS places_gagnees, st.name
ORDER BY res.position;

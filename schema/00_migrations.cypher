// =============================================================================
//  Graphe F1 — migrations du schéma, appliquées avant les contraintes
// =============================================================================
//
//  Chaque instruction est idempotente : sur une base neuve elle ne fait rien.
//  Elles ne touchent qu'aux étiquettes du modèle F1.
// -----------------------------------------------------------------------------

// 2026-10-17 — pays et nationalités passent d'un nœud par libellé de l'API
// (Country {name: 'UK'}, Nationality {name: 'British'}) à un nœud commun par code
// ISO 3166 alpha-3 (:Country:Nationality {iso3: 'GBR'}).
DROP CONSTRAINT country_name_unique IF EXISTS;
DROP CONSTRAINT nationality_name_unique IF EXISTS;
DROP CONSTRAINT country_name_type IF EXISTS;
DROP CONSTRAINT nationality_name_exists IF EXISTS;
DROP CONSTRAINT nationality_name_type IF EXISTS;
MATCH (n) WHERE (n:Country OR n:Nationality) AND n.iso3 IS NULL DETACH DELETE n;

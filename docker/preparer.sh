#!/bin/sh
# Contrôles avant le premier `docker compose up`, et création des répertoires des volumes.
#
#   docker/preparer.sh                         # contrôles + répertoires
#   docker/preparer.sh --amorcer donnees/brut  # + recopie d'un cache existant : évite
#                                              #   une heure de requêtes à l'API
# Échoue au premier problème, avec un message qui le nomme.
set -eu
cd "$(dirname "$0")/.."

ok()    { echo "  ok      $*"; }
echec() { echo "  ÉCHEC   $*" >&2; exit 1; }

echo "Préparation de la pile f1-graph"
command -v docker >/dev/null || echec "docker introuvable"
docker compose version >/dev/null 2>&1 || echec "plugin 'docker compose' introuvable"
ok "$(docker compose version)"
docker info >/dev/null 2>&1 || echec "démon Docker injoignable (droits sur /var/run/docker.sock ?)"
ok "démon Docker joignable"

[ -f .env.docker ] || echec ".env.docker absent : cp .env.docker.example .env.docker, puis le renseigner"
# Lecture ligne à ligne, et non `. ./.env.docker` : une valeur comme CRON_DELTA
# contient des espaces, que le shell prendrait pour une commande.
if grep -q "$(printf '\r')" .env.docker; then echec ".env.docker a des fins de ligne Windows (CRLF) : dos2unix .env.docker"; fi
while IFS= read -r ligne || [ -n "${ligne}" ]; do
  case "${ligne}" in ''|'#'*) continue ;; esac
  export "${ligne%%=*}=${ligne#*=}"
done < .env.docker
ok ".env.docker lu"

[ "${NEO4J_PASSWORD}" != "changez-moi-au-moins-8-caracteres" ] || echec "NEO4J_PASSWORD encore à sa valeur d'exemple"
[ "${#NEO4J_PASSWORD}" -ge 8 ] || echec "NEO4J_PASSWORD trop court : Neo4j exige 8 caractères au moins"
[ "${HOTE_UID}" = "$(id -u)" ] || echec "HOTE_UID=${HOTE_UID} mais id -u=$(id -u) : les fichiers des volumes seraient illisibles"
[ "${HOTE_GID}" = "$(id -g)" ] || echec "HOTE_GID=${HOTE_GID} mais id -g=$(id -g)"
ok "utilisateur ${HOTE_UID}:${HOTE_GID}"

for port in "${NEO4J_HTTP_PORT_HOTE}" "${NEO4J_BOLT_PORT_HOTE}" "${WEB_PORT_HOTE}"; do
  if ss -ltnH "( sport = :${port} )" 2>/dev/null | grep -q .; then
    # Déjà pris : ce n'est acceptable que si c'est notre propre pile qui tourne.
    docker compose --env-file .env.docker ps --status running --services 2>/dev/null | grep -qxE 'neo4j|web' \
      || echec "port hôte ${port} déjà utilisé : changer NEO4J_*_PORT_HOTE dans .env.docker"
  fi
done
ok "ports hôte ${NEO4J_HTTP_PORT_HOTE}, ${NEO4J_BOLT_PORT_HOTE} et ${WEB_PORT_HOTE} disponibles"

for rep in "${NEO4J_DONNEES_HOTE}" "${NEO4J_JOURNAUX_HOTE}" "${F1_DONNEES_HOTE}"; do
  mkdir -p "${rep}"
  [ -w "${rep}" ] || echec "répertoire ${rep} non inscriptible par $(id -un)"
done
ok "répertoires des volumes prêts"

if [ "${1:-}" = "--amorcer" ]; then
  source_cache="${2:?--amorcer exige le chemin d'un cache brut (ex. donnees/brut)}"
  [ -d "${source_cache}" ] || echec "cache ${source_cache} introuvable"
  mkdir -p "${F1_DONNEES_HOTE}/brut"
  cp -a "${source_cache}/." "${F1_DONNEES_HOTE}/brut/"
  ok "cache amorcé depuis ${source_cache} ($(find "${F1_DONNEES_HOTE}/brut" -name 'offset-*.json' ! -name '*.meta.json' | wc -l) pages)"
fi

docker compose --env-file .env.docker config --quiet || echec "compose.yaml invalide avec ces valeurs"
ok "compose.yaml valide"
echo "Prêt : docker compose --env-file .env.docker up -d --build"

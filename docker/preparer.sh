#!/bin/sh
# Contrôles avant le premier `docker compose up`, et création des répertoires des volumes.
#
#   sh docker/preparer.sh                         # contrôles + répertoires
#   sh docker/preparer.sh --amorcer donnees/brut  # + recopie d'un cache existant : évite
#                                                 #   une heure de requêtes à l'API
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

[ -f .env ] || echec ".env absent : cp .env.example .env, puis remplacer chaque valeur « password_… »"
# Lecture ligne à ligne, et non `. ./.env` : une valeur comme CRON_DELTA contient des
# espaces et des « ; », que le shell prendrait pour des commandes.
if grep -q "$(printf '\r')" .env; then echec ".env a des fins de ligne Windows (CRLF) : dos2unix .env"; fi
while IFS= read -r ligne || [ -n "${ligne}" ]; do
  case "${ligne}" in ''|'#'*) continue ;; esac
  export "${ligne%%=*}=${ligne#*=}"
done < .env
ok ".env lu"

if grep -qE '^[A-Z_]+=password_' .env; then
  echec "valeur(s) d'exemple encore présente(s) : $(grep -oE '^[A-Z_]+=password_' .env | cut -d= -f1 | tr '\n' ' ')"
fi
[ "${#NEO4J_PASSWORD}" -ge 8 ] || echec "NEO4J_PASSWORD trop court : Neo4j exige 8 caractères au moins"
ok "secrets renseignés"

case "${NEO4J_EDITION}" in
  community) ok "Neo4j Community" ;;
  enterprise)
    case "${NEO4J_ACCEPT_LICENSE_AGREEMENT}" in
      yes|eval) ok "Neo4j Enterprise, licence acceptée (${NEO4J_ACCEPT_LICENSE_AGREEMENT})" ;;
      *) echec "Enterprise : lire la licence Neo4j, puis NEO4J_ACCEPT_LICENSE_AGREEMENT=yes (licence commerciale) ou eval (évaluation)" ;;
    esac ;;
  *) echec "NEO4J_EDITION=${NEO4J_EDITION} : community ou enterprise attendu" ;;
esac

# Mémoire de Neo4j : limite du conteneur >= tas + cache de pages + 1 Go de mémoire
# native. En dessous, la JVM se fige et le healthcheck expire (constaté le 29/10/2026).
taille_mo() {
  case "$1" in
    *[gG]) n="${1%[gG]}"; m=1024 ;;
    *[mM]) n="${1%[mM]}"; m=1 ;;
    *) echec "taille « $1 » illisible : écrire par exemple 768m ou 3g" ;;
  esac
  case "${n}" in ''|*[!0-9]*) echec "taille « $1 » illisible : nombre entier attendu (768m, 3g)" ;; esac
  echo $(( n * m ))
}
requis=$(( $(taille_mo "${NEO4J_HEAP}") + $(taille_mo "${NEO4J_PAGECACHE}") + 1024 ))
limite=$(taille_mo "${NEO4J_MEM_LIMIT}")
[ "${limite}" -ge "${requis}" ] \
  || echec "NEO4J_MEM_LIMIT=${NEO4J_MEM_LIMIT} (${limite} Mo) < tas ${NEO4J_HEAP} + cache ${NEO4J_PAGECACHE} + 1 Go (${requis} Mo)"
ok "mémoire Neo4j : ${limite} Mo pour ${requis} Mo requis"

[ "${HOTE_UID}" = "$(id -u)" ] || echec "HOTE_UID=${HOTE_UID} mais id -u=$(id -u) : les fichiers des volumes seraient illisibles"
[ "${HOTE_GID}" = "$(id -g)" ] || echec "HOTE_GID=${HOTE_GID} mais id -g=$(id -g)"
gid_socket=$(stat -c %g /var/run/docker.sock 2>/dev/null || echo "?")
[ "${DOCKER_GID}" = "${gid_socket}" ] || echec "DOCKER_GID=${DOCKER_GID} mais le socket Docker appartient au groupe ${gid_socket} (sauvegarde impossible)"
ok "utilisateur ${HOTE_UID}:${HOTE_GID}, groupe Docker ${DOCKER_GID}"

for port in "${NEO4J_HTTP_PORT_HOTE}" "${NEO4J_BOLT_PORT_HOTE}" "${WEB_PORT_HOTE}"; do
  if ss -ltnH "( sport = :${port} )" 2>/dev/null | grep -q .; then
    # Déjà pris : ce n'est acceptable que si c'est notre propre pile qui tourne.
    docker compose ps --status running --services 2>/dev/null | grep -qxE 'neo4j|web' \
      || echec "port hôte ${port} déjà utilisé : changer *_PORT_HOTE dans .env"
  fi
done
ok "ports hôte ${NEO4J_HTTP_PORT_HOTE}, ${NEO4J_BOLT_PORT_HOTE} et ${WEB_PORT_HOTE} disponibles"

for rep in "${NEO4J_DONNEES_HOTE}" "${NEO4J_JOURNAUX_HOTE}" "${F1_DONNEES_HOTE}" "${SAUVEGARDES_HOTE}"; do
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

docker compose config --quiet || echec "compose.yaml invalide avec ces valeurs"
ok "compose.yaml valide"
echo "Prêt : docker compose up -d --build"

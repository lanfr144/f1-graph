#!/bin/sh
# Point d'entrée du chargeur.
#  1. Chargement initial : `pipeline.py --delta`. Sur une base vide, toutes les
#     saisons sont absentes : le delta est un chargement complet, repris là où il
#     s'est arrêté si le conteneur a été stoppé en cours de route.
#  2. Puis supercronic exécute le même delta selon CRON_DELTA.
# Tout est journalisé sur la sortie standard : `docker compose logs -f chargeur`.
set -eu

: "${CRON_DELTA:?CRON_DELTA manquant (ex. '17 20,23 * * 0;17 7 * * 1', expressions séparées par ;)}"
: "${PIPELINE_OPTIONS?PIPELINE_OPTIONS manquant (peut être vide)}"
: "${NEO4J_URI:?NEO4J_URI manquant}"

horodatage() { date '+%Y-%m-%d %H:%M:%S%z'; }
journal() { echo "$(horodatage) [demarrer] $*"; }

COMMANDE="python /app/pipeline.py --delta ${PIPELINE_OPTIONS}"

journal "chargeur f1-graph : données ${F1_DONNEES}, base ${NEO4J_URI}, fuseau ${TZ:-UTC}"
journal "diagnostic réseau : $(getent hosts "$(echo "$NEO4J_URI" | sed -E 's#.*://([^:/]+).*#\1#')" || echo 'hôte Neo4j non résolu')"

# Chargement initial au premier plan, SIGTERM relayé : `docker stop` l'interrompt
# proprement (état enregistré) au lieu de le tuer.
journal "chargement initial ou reprise : ${COMMANDE}"
${COMMANDE} &
PID=$!
trap 'journal "arrêt demandé : interruption du chargement (pid ${PID})"; kill -TERM ${PID} 2>/dev/null; wait ${PID}; exit 143' TERM INT
CODE=0
wait ${PID} || CODE=$?
trap - TERM INT
if [ "${CODE}" -eq 0 ]; then
  journal "chargement initial terminé sans erreur"
else
  journal "ATTENTION : chargement initial terminé avec le code ${CODE} ; le prochain delta reprendra les étapes en défaut (voir 'python /app/pipeline.py --etat')"
fi

# Plusieurs créneaux possibles, séparés par « ; » (dimanche soir ET lundi matin…).
: > /tmp/f1.crontab
echo "${CRON_DELTA}" | tr ';' '\n' | while IFS= read -r expression; do
  expression=$(echo "${expression}" | sed 's/^ *//; s/ *$//')
  [ -n "${expression}" ] && printf '%s %s\n' "${expression}" "${COMMANDE}" >> /tmp/f1.crontab
done
[ -s /tmp/f1.crontab ] || { journal "ÉCHEC : CRON_DELTA ne contient aucune expression"; exit 1; }
journal "planification des deltas :"
sed 's/^/    /' /tmp/f1.crontab
supercronic -no-reap -test /tmp/f1.crontab
# -no-reap : docker-init (init: true) est le PID 1 et récolte déjà les zombies.
# -passthrough-logs : le journal du pipeline passe tel quel, sans enveloppe supercronic.
exec supercronic -no-reap -passthrough-logs /tmp/f1.crontab

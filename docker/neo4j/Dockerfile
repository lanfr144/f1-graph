# Neo4j, édition au choix : NEO4J_EDITION=community ou enterprise (fichier .env).
# Les deux bases sont épinglées par empreinte : seuls les correctifs de sécurité
# apportés par `apt-get upgrade` varient d'une construction à l'autre.
#
# Enterprise : licence commerciale, ou évaluation. Son acceptation est une décision
# de l'utilisateur (NEO4J_ACCEPT_LICENSE_AGREEMENT dans .env), jamais un défaut.
# Elle apporte les 87 contraintes d'existence et de type (schema/02_…), que charger.py
# applique alors automatiquement.
ARG NEO4J_EDITION

FROM neo4j:2026.08.1-community@sha256:d8f4c156caa3af76499134947deb11d13042e471d9733060449f2a01eb7a248e AS community
FROM neo4j:2026.08.1-enterprise@sha256:e8402c7f4687a27bf4fa854bb7020777aa3cc971c5b202334509ca452f1f6c44 AS enterprise

# Une valeur autre que community ou enterprise fait échouer la construction ici.
FROM ${NEO4J_EDITION}
ARG NEO4J_EDITION

# Mise à jour et outils de diagnostic réseau, en une seule couche.
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get check \
 && apt-get install -y --no-install-recommends \
      iproute2 net-tools iputils-ping bind9-dnsutils curl traceroute \
 && apt-get autoremove -y \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Échouer à la construction, et non au démarrage, si un prérequis manque.
RUN for outil in ss netstat ip ifconfig ping dig nslookup curl traceroute; do \
      command -v "$outil" >/dev/null || { echo "construction : outil manquant : $outil" >&2; exit 1; }; \
    done \
 && test -x /var/lib/neo4j/bin/cypher-shell \
      || { echo "construction : /var/lib/neo4j/bin/cypher-shell manquant (healthcheck impossible)" >&2; exit 1; } \
 && test -x /var/lib/neo4j/bin/neo4j-admin \
      || { echo "construction : neo4j-admin manquant (sauvegarde impossible)" >&2; exit 1; } \
 && echo "${NEO4J_EDITION}" > /var/lib/neo4j/EDITION_F1

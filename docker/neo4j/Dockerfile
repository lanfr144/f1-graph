# Neo4j Community, base épinglée par empreinte : seuls les correctifs de sécurité
# apportés par `apt-get upgrade` varient d'une construction à l'autre.
FROM neo4j:2026.08.1-community@sha256:d8f4c156caa3af76499134947deb11d13042e471d9733060449f2a01eb7a248e

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
      || { echo "construction : /var/lib/neo4j/bin/cypher-shell manquant (healthcheck impossible)" >&2; exit 1; }

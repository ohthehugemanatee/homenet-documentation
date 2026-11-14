#!/usr/bin/env bash
set -euo pipefail

sql="CREATE DATABASE ci_upgrade;
CREATE TABLE ci_upgrade.t (id INT PRIMARY KEY, v VARCHAR(16));
INSERT INTO ci_upgrade.t VALUES (1, 'one'), (2, 'two'), (3, 'three');"

# shellcheck disable=SC2016 # $MYSQL_ROOT_PASSWORD expands in the container
kubectl -n "$NAMESPACE" exec "$POD" -c "$CONTAINER" -- \
  sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -h127.0.0.1 -e "$1"' sh "$sql"

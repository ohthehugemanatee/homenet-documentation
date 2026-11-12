#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC2016 # $MYSQL_ROOT_PASSWORD expands in the container
rows=$(kubectl -n "$NAMESPACE" exec "$POD" -c "$CONTAINER" -- \
  sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -h127.0.0.1 -N -e "$1"' sh \
  'SELECT GROUP_CONCAT(v ORDER BY id) FROM ci_upgrade.t')

if [ "$rows" != "one,two,three" ]; then
  echo "expected one,two,three but read: $rows" >&2
  exit 1
fi

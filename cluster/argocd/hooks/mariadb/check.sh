#!/bin/sh
# Read-only. Runs inside the mariadb container as `sh -c "<this file>"`.
out=$(mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -h127.0.0.1 -N \
  -e 'SELECT COUNT(*) FROM information_schema.SCHEMATA' 2>&1) || {
  echo "$out"
  echo 'mariadb does not answer a query'
  exit 1
}
if ! out=$(mysqlcheck --all-databases --fast --silent \
  -uroot -p"$MYSQL_ROOT_PASSWORD" -h127.0.0.1 2>&1) || [ -n "$out" ]; then
  echo "$out"
  echo 'mysqlcheck reported problems'
  exit 1
fi

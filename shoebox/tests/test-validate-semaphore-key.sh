#!/usr/bin/env bash
# Unit tests for shoebox/scripts/validate-semaphore-key.sh.
# Verifies that the validator catches the malformed-value patterns that cause
# Semaphore's "illegal base64 data at input byte N" error when adding keys.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALIDATOR="${SCRIPT_DIR}/../scripts/validate-semaphore-key.sh"

failures=0

assert() {
  local desc=$1
  local value=$2
  local expected=$3   # "pass" or "fail"

  if printf '%s' "$value" | bash "$VALIDATOR" >/dev/null 2>&1; then
    actual="pass"
  else
    actual="fail"
  fi

  if [ "$actual" = "$expected" ]; then
    echo "  OK   $desc"
  else
    echo "  FAIL $desc (expected $expected, got $actual)"
    failures=$((failures + 1))
  fi
}

echo "Running validate-semaphore-key tests..."

assert "valid 32-byte standard base64" \
  "$(openssl rand -base64 32 | tr -d '\n')" pass

# The actual bug we hit in production: Python's token_urlsafe uses '-' and '_'.
assert "Python token_urlsafe(32) rejected" \
  "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" fail

assert "URL-safe base64 with dash at position 3" \
  "abc-EFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqr==" fail

assert "URL-safe base64 with underscore" \
  "abc_EFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqr==" fail

assert "wrong length — decodes to 16 bytes" \
  "$(openssl rand -base64 16 | tr -d '\n')" fail

assert "wrong length — decodes to 64 bytes" \
  "$(openssl rand -base64 64 | tr -d '\n')" fail

assert "leading whitespace" \
  " $(openssl rand -base64 32 | tr -d '\n')" fail

assert "trailing whitespace" \
  "$(openssl rand -base64 32 | tr -d '\n') " fail

assert "embedded tab" \
  "$(printf 'abc\tDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcde=')" fail

assert "empty value" "" fail

assert "non-base64 garbage" "this is not base64 at all !!!" fail

echo ""
if [ "$failures" -eq 0 ]; then
  echo "All validate-semaphore-key tests passed."
else
  echo "$failures test(s) failed."
  exit 1
fi

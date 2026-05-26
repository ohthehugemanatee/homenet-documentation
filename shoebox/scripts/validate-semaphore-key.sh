#!/usr/bin/env bash
# Validate a SEMAPHORE_ACCESS_KEY_ENCRYPTION value.
#
# Semaphore base64-decodes this env var to obtain a 32-byte AES key.
# Common ways to produce a malformed value:
#   - Using URL-safe base64 (Python's secrets.token_urlsafe, base64 -w0 with
#     -i URL-safe variants) which uses '-' and '_' — invalid in standard base64.
#     Decoding fails with "illegal base64 data at input byte 3" when the dash
#     happens to land at that position.
#   - Embedded newlines from a missing `| tr -d '\n'`.
#   - Wrong byte length (not 32 after decode).
#
# Reads the value from $1 or stdin. Exits 0 if valid, non-zero with a clear
# error message on stderr otherwise.

set -euo pipefail

val="${1-}"
if [ -z "$val" ]; then
  val=$(cat)
fi

if [ -z "$val" ]; then
  echo "ERROR: SEMAPHORE_ACCESS_KEY_ENCRYPTION is empty" >&2
  exit 1
fi

if printf '%s' "$val" | LC_ALL=C grep -q '[[:space:]]'; then
  echo "ERROR: SEMAPHORE_ACCESS_KEY_ENCRYPTION contains whitespace" >&2
  printf "Hint: regenerate with: openssl rand -base64 32 | tr -d '\\\\n'\n" >&2
  exit 1
fi

if printf '%s' "$val" | LC_ALL=C grep -q '[-_]'; then
  echo "ERROR: SEMAPHORE_ACCESS_KEY_ENCRYPTION contains URL-safe base64 chars (- or _)." >&2
  echo "Semaphore requires STANDARD base64. Causes the 'illegal base64 data at input byte N'" >&2
  echo "error when adding keys in the UI." >&2
  printf "Hint: regenerate with: openssl rand -base64 32 | tr -d '\\\\n'\n" >&2
  exit 1
fi

decoded_len=$(printf '%s' "$val" | base64 -d 2>/dev/null | wc -c | tr -d ' ')
if [ "$decoded_len" != "32" ]; then
  echo "ERROR: SEMAPHORE_ACCESS_KEY_ENCRYPTION must base64-decode to 32 bytes, got ${decoded_len}." >&2
  printf "Hint: regenerate with: openssl rand -base64 32 | tr -d '\\\\n'\n" >&2
  exit 1
fi

exit 0

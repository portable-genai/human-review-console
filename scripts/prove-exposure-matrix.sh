#!/usr/bin/env bash
# Drive the WHOLE exposure matrix against this service over a REAL socket, from a REAL
# non-loopback address, and require every cell to refuse or to refuse to boot.
#
# The matrix is the profile variable's states crossed with the S2S secret's states, each probed
# with and without the seeded-persona header:
#
#      REVIEW_PROFILE: unset | empty | Local (mis-capitalised) | local | onprem | gcp | platform
#    REVIEW_S2S_TOKEN: unset | empty | set
#       X-Dev-Persona: absent | approver
#
# Why the whole matrix rather than the one case tests/test_serving_path_exposure.py covers: the
# defect this script was written for lived in a cell nobody had run. With REVIEW_PROFILE=local
# chosen DELIBERATELY and REVIEW_S2S_TOKEN SET (an ordinary deployment shape), the exposure
# guard's posture read "... and the token is NOT set", so SETTING a service credential switched
# the guard off for the END-USER routes it was protecting, and a LAN peer with no Authorization
# header and no X-Dev-Persona got the seeded persona list and the maker-checker queue.
#
# The fix is not a wider boolean. The guard now asks the IDENTITY ADAPTER the active binding
# names whether it verifies the end user (src/review_console/ports/identity.py), so a service
# credential cannot speak for end-user routes at all. This script is the standing proof, cell by
# cell.
#
# tests/test_serving_path_exposure.py covers the same ground with a TestClient, which is faster
# and runs in the offline gate. This runs uvicorn and a socket, because a TestClient proves what
# the app OBJECT does and only a bound server proves what a stranger gets.
#
# EXPECTED, per cell: either the process refuses to BOOT (the profile names nothing this service
# binds), or every route answers the LAN peer 503. A profile SET to an empty value is no choice
# rather than a boot failure here, and lands in the same place as an unset one: guarded.
# The two profiles with a verifying end-user identity
# adapter, gcp and platform, are the deliberate exception and are asserted separately at the
# bottom: their end-user routes must answer 401 with no IAP assertion and the S2S route 503,
# while /healthz stays reachable because the platform fronts that deployment and it carries no
# per-caller data.
#
# bash 3.2 compatible on purpose (that is what macOS ships): no arrays, because `set -u` plus an
# empty array expansion is an error there and a proof script that cannot run is worth nothing.
#
# Offline: the address used is this machine's own primary LAN address, discovered from the local
# routing table. Nothing is sent anywhere but to this host.
#
#   scripts/prove-exposure-matrix.sh
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PROVE_PORT:-8123}"
LOG="${TMPDIR:-/tmp}/prove-exposure-server.log"
BODY="${TMPDIR:-/tmp}/prove-exposure-body"
PYBIN="${PROVE_PYTHON:-python3}"
PAYLOAD='{"maker":"attacker@evil.example","tenant":"demo-bank","action":"payout.release","subject":"acct-4471","summary":"probe from a LAN peer","severity":"high","source_key":"prove-exposure"}'

# This machine's primary non-loopback IPv4 address. connect() on a UDP socket sends no packet; it
# only selects a route and therefore a source address.
LAN_IP="$("$PYBIN" -c '
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("192.0.2.1", 9))
    print(s.getsockname()[0])
finally:
    s.close()
')"
case "$LAN_IP" in
  ""|127.*) echo "no non-loopback address on this host; cannot prove the LAN refusal" >&2; exit 1 ;;
esac
echo "   lan=$LAN_IP port=$PORT python=$PYBIN"

SERVER_PID=""
stop_server() {
  [ -n "$SERVER_PID" ] || return 0
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
  SERVER_PID=""
}
trap stop_server EXIT

# Nothing may be listening on the port when a cell starts. A server left over from the previous
# cell would answer the next cell's probes from the PREVIOUS cell's environment, and every cell
# would report the first cell's posture: a whole matrix of green ticks about one configuration.
wait_for_port_closed() {
  for _ in $(seq 1 100); do
    curl -s --max-time 1 -o /dev/null "http://127.0.0.1:$PORT/healthz" || return 0
    sleep 0.1
  done
  return 1
}

# $1 = the profile value, or the literal word UNSET to remove the variable.
# $2 = the token value, or the literal word UNSET to remove it.
#
# The command is assembled as a string and `eval`ed because every -u flag must precede the first
# NAME=VALUE (BSD env stops parsing options at the first assignment, so `env VAR= -u OTHER cmd`
# silently tries to run a command called "-u") and because an EMPTY value has to survive as a
# present-but-empty assignment. Every fragment below is a literal from this file; nothing here
# comes from the network.
#
# `exec`, so the background job IS uvicorn rather than a shell wrapping it. Without it `kill`
# reaps the wrapper and leaves the server holding the port, and the next cell is answered by the
# previous cell's process.
start_server() {
  if ! wait_for_port_closed; then
    echo "     FAILED: port $PORT is still serving; a previous cell's process would answer" >&2
    exit 1
  fi
  : >"$LOG"
  flags="-u REVIEW_ALLOW_INSECURE_DEMO -u REVIEW_S2S_ALLOWED_CALLERS -u REVIEW_S2S_AUDIENCE"
  assignments="PYTHONPATH=src REVIEW_DB_PATH=:memory: REVIEW_AUDIT_PATH=:memory:"
  if [ "$1" = "UNSET" ]; then
    flags="$flags -u REVIEW_PROFILE"
  else
    assignments="$assignments REVIEW_PROFILE='$1'"
  fi
  if [ "$2" = "UNSET" ]; then
    flags="$flags -u REVIEW_S2S_TOKEN"
  else
    assignments="$assignments REVIEW_S2S_TOKEN='$2'"
  fi
  eval "exec env $flags $assignments '$PYBIN' -m uvicorn 'review_console.api.app:app' \
        --host 0.0.0.0 --port '$PORT'" >"$LOG" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 60); do
    kill -0 "$SERVER_PID" 2>/dev/null || return 1
    curl -s --max-time 1 -o /dev/null "http://127.0.0.1:$PORT/healthz" && return 0
    sleep 0.2
  done
  return 0
}

# $1 method, $2 path, $3 "persona" to send X-Dev-Persona: approver, "bare" to send nothing.
# Leaves the status in CODE and the body in $BODY. Written as four explicit branches rather than
# an assembled argument list: this is the file that decides whether a refusal happened, so it
# stays readable at a glance.
CODE=""
request() {
  url="http://$LAN_IP:$PORT$2"
  if [ "$1" = "GET" ]; then
    if [ "$3" = "persona" ]; then
      CODE="$(curl -s -o "$BODY" -w '%{http_code}' --max-time 5 \
        -H 'X-Dev-Persona: approver' "$url" || echo 000)"
    else
      CODE="$(curl -s -o "$BODY" -w '%{http_code}' --max-time 5 "$url" || echo 000)"
    fi
  else
    if [ "$3" = "persona" ]; then
      CODE="$(curl -s -o "$BODY" -w '%{http_code}' --max-time 5 -X POST \
        -H 'Content-Type: application/json' -H 'X-Dev-Persona: approver' \
        -d "$PAYLOAD" "$url" || echo 000)"
    else
      CODE="$(curl -s -o "$BODY" -w '%{http_code}' --max-time 5 -X POST \
        -H 'Content-Type: application/json' -d "$PAYLOAD" "$url" || echo 000)"
    fi
  fi
  printf '     %-4s %-26s %-7s -> %s  %s\n' "$1" "$2" "$3" "$CODE" "$(head -c 110 "$BODY")"
}

# Every route the app serves, including the ones that need no identity at all: a deployment that
# can authenticate nobody has no business answering a stranger even about its own health or its
# workflow catalogue. Each is probed twice, with and without the seeded-persona header.
probe_every_route() {
  want="$1"
  failed=0
  for persona in bare persona; do
    request GET  /healthz              "$persona"; [ "$CODE" = "$want" ] || failed=1
    request GET  /v1/personas          "$persona"; [ "$CODE" = "$want" ] || failed=1
    request GET  /v1/reviews           "$persona"; [ "$CODE" = "$want" ] || failed=1
    request GET  /v1/cases             "$persona"; [ "$CODE" = "$want" ] || failed=1
    request GET  /v1/workflows         "$persona"; [ "$CODE" = "$want" ] || failed=1
    request POST /v1/service/reviews   "$persona"; [ "$CODE" = "$want" ] || failed=1
    request POST /v1/audit/ping        "$persona"; [ "$CODE" = "$want" ] || failed=1
  done
  return "$failed"
}

FAILURES=0

# One matrix cell: profile $2, token $3. Every route must answer 503, or the process must have
# refused to boot for a reason that names the profile variable.
run_cell() {
  echo "-- $1 --"
  if ! start_server "$2" "$3"; then
    echo "     the process REFUSED TO BOOT, which is a stronger refusal than a 503:"
    # pipefail is on, so a grep that matches nothing would kill the script; never let the
    # DIAGNOSTIC decide the verdict.
    { grep -E 'Error|Exception|refus' "$LOG" || tail -5 "$LOG"; } | tail -2 | sed 's/^/       /'
    stop_server
    # A crash is only a REFUSAL if it is the refusal we claimed. Anything else (a port clash, a
    # typo in this script, a missing dependency) would otherwise be reported as a pass, which is
    # exactly the kind of falsely-green proof this whole exercise exists to remove.
    if ! grep -q "REVIEW_PROFILE" "$LOG"; then
      echo "     FAILED: the process died, but not because of REVIEW_PROFILE. See $LOG."
      FAILURES=$((FAILURES + 1))
    fi
    return 0
  fi
  if probe_every_route 503; then
    echo "     every route refused the LAN peer"
  else
    echo "     FAILED: a route answered something other than 503 to a non-loopback peer"
    FAILURES=$((FAILURES + 1))
  fi
  stop_server
}

echo "== the exposure matrix: profile x S2S token x persona header, from $LAN_IP =="
for token_label in UNSET EMPTY SET; do
  case "$token_label" in
    UNSET) token=UNSET ;;
    EMPTY) token="" ;;
    *)     token="not-a-real-secret" ;;
  esac
  run_cell "profile UNSET,               token $token_label" UNSET   "$token"
  run_cell "profile EMPTY,               token $token_label" ""      "$token"
  run_cell "profile 'Local' (typo),      token $token_label" "Local" "$token"
  run_cell "profile local (DELIBERATE),  token $token_label" local   "$token"
  run_cell "profile onprem,              token $token_label" onprem  "$token"
done

# ------------------------------------------------------------------------------------------ #
# The deliberate exception, asserted rather than assumed: gcp and platform bind an identity
# adapter that VERIFIES a signed IAP assertion, so their end-user routes authenticate themselves
# and the exposure guard stands down. That is only defensible if the end-user routes actually
# refuse an uncredentialed peer, so prove it rather than taking the declaration's word for it.
# ------------------------------------------------------------------------------------------ #
verifying_profile() {
  echo "-- profile $1 (verifying identity adapter): guard stands down, the ROUTES refuse --"
  if ! start_server "$1" "not-a-real-secret"; then
    echo "     FAILED: the $1 profile did not boot"
    FAILURES=$((FAILURES + 1))
    return 0
  fi
  request GET /v1/reviews persona
  if [ "$CODE" != "401" ]; then
    echo "     FAILED: /v1/reviews must answer 401 with no IAP assertion"
    FAILURES=$((FAILURES + 1))
  fi
  request GET /v1/cases persona
  if [ "$CODE" != "401" ]; then
    echo "     FAILED: /v1/cases must answer 401 with no IAP assertion"
    FAILURES=$((FAILURES + 1))
  fi
  request POST /v1/service/reviews persona
  if [ "$CODE" != "503" ]; then
    echo "     FAILED: /v1/service/reviews must answer 503 with no S2S identity policy"
    FAILURES=$((FAILURES + 1))
  fi
  request POST /v1/audit/ping persona
  if [ "$CODE" != "503" ]; then
    echo "     FAILED: /v1/audit/ping must answer 503 with no S2S identity policy"
    FAILURES=$((FAILURES + 1))
  fi
  request GET /v1/personas persona
  if [ "$CODE" != "200" ] || [ "$(cat "$BODY")" != "[]" ]; then
    echo "     FAILED: /v1/personas must be empty outside the seeded-persona profile"
    FAILURES=$((FAILURES + 1))
  fi
  request GET /healthz bare
  if [ "$CODE" != "200" ]; then
    echo "     FAILED: a fronted deployment must stay health-checkable"
    FAILURES=$((FAILURES + 1))
  fi
  echo "     no end-user result reached the uncredentialed peer"
  stop_server
}

verifying_profile gcp
verifying_profile platform

if [ "$FAILURES" -ne 0 ]; then
  echo "== EXPOSURE MATRIX: $FAILURES FAILING CELLS =="
  exit 1
fi
echo "== EXPOSURE MATRIX: EVERY CELL REFUSED =="

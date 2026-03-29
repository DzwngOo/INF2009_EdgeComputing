#!/usr/bin/env bash
# test_network_resilience.sh
#
# Network-resilience test for the MRT cabin monitoring pipeline.
#
# Applies tc-netem impairment (200 ms RTT + 5 % packet loss) on the
# loopback interface and verifies that the system recovers (last-known
# state persists and fresh data resumes) within 3 seconds of the
# impairment being removed.
#
# Prerequisites:
#   sudo apt-get install -y iproute2 mosquitto-clients bc
#   Note: this script requires Linux — it uses tc-netem (iproute2) and
#         GNU date (%s%3N millisecond format), neither of which is
#         available on macOS or BSD without additional tooling.
#
# Usage:
#   sudo bash test_network_resilience.sh [BROKER_HOST [BROKER_PORT [TOPIC]]]
#
# Defaults:
#   BROKER_HOST=127.0.0.1
#   BROKER_PORT=1884
#   TOPIC=mrt/cabin1/vision
#
# The script must be run as root (or with sudo) because tc requires
# CAP_NET_ADMIN to modify qdisc rules.

set -euo pipefail

BROKER_HOST="${1:-127.0.0.1}"
BROKER_PORT="${2:-1884}"
TOPIC="${3:-mrt/cabin1/vision}"

IFACE="lo"          # loopback — same interface used by the MQTT loopback broker
NETEM_DELAY="100ms" # one-way delay → ~200 ms RTT
NETEM_LOSS="5%"

RECOVERY_TIMEOUT_S=3
MSG_WAIT_S=10       # how long to wait for a message while impairment is active

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${YELLOW}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
fail() { echo -e "${RED}[FAIL]${NC}  $*"; }

# ── sanity checks ─────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    fail "This script must be run as root (use: sudo bash $0)."
    exit 1
fi

for cmd in tc mosquitto_pub mosquitto_sub bc; do
    if ! command -v "$cmd" &>/dev/null; then
        fail "Required command not found: $cmd"
        echo "  Install with: sudo apt-get install -y iproute2 mosquitto-clients bc"
        exit 1
    fi
done

# ── helpers ───────────────────────────────────────────────────────────────────
apply_netem() {
    if tc qdisc show dev "$IFACE" | grep -q "netem"; then
        tc qdisc change dev "$IFACE" root netem delay "$NETEM_DELAY" loss "$NETEM_LOSS"
    else
        tc qdisc add dev "$IFACE" root netem delay "$NETEM_DELAY" loss "$NETEM_LOSS"
    fi
    info "tc-netem applied on $IFACE: delay=$NETEM_DELAY (RTT ~200 ms), loss=$NETEM_LOSS"
}

remove_netem() {
    tc qdisc del dev "$IFACE" root 2>/dev/null || true
    info "tc-netem removed from $IFACE — link restored to normal."
}

# Always clean up netem on exit so the interface is not left impaired
trap remove_netem EXIT

# ── Step 1: capture last-known state ─────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════"
echo "  Network-Resilience Test"
echo "  Broker : ${BROKER_HOST}:${BROKER_PORT}  Topic: ${TOPIC}"
echo "════════════════════════════════════════════════════════"
echo ""

info "Step 1/4: Capturing last-known state from topic '${TOPIC}' …"
LAST_KNOWN=$(mosquitto_sub -h "$BROKER_HOST" -p "$BROKER_PORT" \
    -t "$TOPIC" -C 1 --quiet -W 5 2>/dev/null || true)

if [[ -z "$LAST_KNOWN" ]]; then
    fail "No message received on '${TOPIC}' within 5 s."
    echo "       Ensure the pipeline (Camera Pi + MQTT broker) is running before this test."
    exit 1
fi
ok "Last-known state captured (first 80 chars): ${LAST_KNOWN:0:80}…"

# ── Step 2: apply network impairment ─────────────────────────────────────────
info "Step 2/4: Applying network impairment …"
apply_netem

# ── Step 3: verify pipeline continues to publish under impairment ─────────────
info "Step 3/4: Verifying pipeline publishes under impairment (wait up to ${MSG_WAIT_S}s) …"
IMPAIRED_MSG=$(mosquitto_sub -h "$BROKER_HOST" -p "$BROKER_PORT" \
    -t "$TOPIC" -C 1 --quiet -W "$MSG_WAIT_S" 2>/dev/null || true)

if [[ -z "$IMPAIRED_MSG" ]]; then
    fail "No message received while impairment was active (${MSG_WAIT_S}s timeout)."
    fail "Last-known state NOT held — pipeline may have crashed or stalled."
    remove_netem
    trap - EXIT
    exit 1
fi
ok "Message received under impairment — last-known state is held."

# ── Step 4: remove impairment and measure recovery time ───────────────────────
info "Step 4/4: Removing impairment and measuring recovery time …"
REMOVE_TIME_MS=$(date +%s%3N)
remove_netem
trap - EXIT   # netem is already removed; cancel the EXIT trap

# Poll for a fresh message within RECOVERY_TIMEOUT_S
RECOVERED=false
RECOVERY_MS=0
DEADLINE_MS=$(( REMOVE_TIME_MS + RECOVERY_TIMEOUT_S * 1000 ))

while [[ $(date +%s%3N) -lt $DEADLINE_MS ]]; do
    MSG=$(mosquitto_sub -h "$BROKER_HOST" -p "$BROKER_PORT" \
        -t "$TOPIC" -C 1 --quiet -W 1 2>/dev/null || true)
    if [[ -n "$MSG" ]]; then
        RECOVERY_MS=$(( $(date +%s%3N) - REMOVE_TIME_MS ))
        RECOVERED=true
        break
    fi
done

# ── Report ────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════"
echo "  Results"
echo "════════════════════════════════════════════════════════"
echo "  Impairment  : delay=${NETEM_DELAY} (RTT ~200 ms), loss=${NETEM_LOSS}"
echo "  Interface   : ${IFACE}"
echo "  Topic       : ${TOPIC}"
echo ""

EXIT_CODE=0
if $RECOVERED; then
    echo "  Recovery time : ${RECOVERY_MS} ms"
    if (( RECOVERY_MS <= RECOVERY_TIMEOUT_S * 1000 )); then
        ok "Recovered within ${RECOVERY_TIMEOUT_S}s target.  ✓"
    else
        fail "Recovery took ${RECOVERY_MS} ms — exceeds ${RECOVERY_TIMEOUT_S}s target.  ✗"
        EXIT_CODE=1
    fi
else
    fail "No message received within ${RECOVERY_TIMEOUT_S}s of impairment removal.  ✗"
    EXIT_CODE=1
fi

echo "════════════════════════════════════════════════════════"
exit $EXIT_CODE

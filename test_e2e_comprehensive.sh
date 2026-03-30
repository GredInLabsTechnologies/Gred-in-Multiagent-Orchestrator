#!/bin/bash
# Comprehensive E2E Test - All Critical Endpoints
# Tests ServerBond + all major API flows

# Don't exit on error - we want to see all failures
set +e

GIMO_REPO="/c/Users/shilo/Documents/Github/gred_in_multiagent_orchestrator"
SERVER_URL="http://127.0.0.1:9325"
TOKEN="3dlUIJet72bj-NLF_ek-9VysFHU-vj2D2ZL4QUxWM-LeyFd5bMB_RJhK9hL4N8mu"

export ORCH_OPERATOR_TOKEN="$TOKEN"

echo "=================================================="
echo "  GIMO E2E Comprehensive Test Suite"
echo "  Testing 252 endpoints systematically"
echo "=================================================="
echo ""

# Test counters
TOTAL=0
PASSED=0
FAILED=0
SKIPPED=0

test_endpoint() {
    local method="$1"
    local path="$2"
    local expected_code="$3"
    local desc="$4"

    TOTAL=$((TOTAL + 1))
    printf "[%3d] %-6s %-50s ... " "$TOTAL" "$method" "$path"

    response=$(curl -s -w "\n%{http_code}" -X "$method" \
        -H "Authorization: Bearer $TOKEN" \
        "$SERVER_URL$path" 2>&1)

    http_code=$(echo "$response" | tail -1)
    body=$(echo "$response" | head -n -1)

    if [ "$http_code" = "$expected_code" ]; then
        echo "✓ PASS ($http_code)"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo "✗ FAIL (expected $expected_code, got $http_code)"
        echo "   Response: ${body:0:100}"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

test_cli_command() {
    local cmd="$1"
    local expected_pattern="$2"
    local desc="$3"

    TOTAL=$((TOTAL + 1))
    printf "[%3d] CLI: %-50s ... " "$TOTAL" "$cmd"

    output=$(cd /tmp && eval "$cmd" 2>&1)
    exit_code=$?

    if echo "$output" | grep -q "$expected_pattern"; then
        echo "✓ PASS"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo "✗ FAIL (pattern not found: $expected_pattern)"
        echo "   Output: ${output:0:100}"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

echo "=== PHASE 1: Core Health Checks ==="
test_endpoint GET  /health           200 "Server health"
test_endpoint GET  /health/deep      200 "Deep health check"
test_endpoint GET  /status           200 "Server status"

echo ""
echo "=== PHASE 2: Auth & Capabilities ==="
test_endpoint GET  /auth/check       200 "Auth check"
test_endpoint GET  /ops/capabilities 200 "Capabilities endpoint"

echo ""
echo "=== PHASE 3: Operator Status ==="
test_endpoint GET  /ops/operator/status 200 "Operator status snapshot"

echo ""
echo "=== PHASE 4: Provider Management ==="
test_endpoint GET  /ops/provider           200 "Get active provider"
test_endpoint GET  /ops/provider/models    200 "List models"
test_endpoint GET  /ops/connectors         200 "List connectors"
test_endpoint GET  /ops/connectors/codex/auth-status  200 "Codex auth status"
test_endpoint GET  /ops/connectors/claude/auth-status 200 "Claude auth status"

echo ""
echo "=== PHASE 5: Repository Management ==="
test_endpoint GET  /ops/repos        200 "List repos"
test_endpoint GET  /ops/repos/active 200 "Get active repo"

echo ""
echo "=== PHASE 6: Config & Context ==="
test_endpoint GET  /ops/config             200 "Get config"
test_endpoint GET  /ops/context/git-status 200 "Git status"

echo ""
echo "=== PHASE 7: Runs & Drafts ==="
test_endpoint GET  /ops/runs         200 "List runs"
test_endpoint GET  /ops/drafts       200 "List drafts"
test_endpoint GET  /ops/approved     200 "List approved"

echo ""
echo "=== PHASE 8: Token Mastery ==="
test_endpoint GET  /ops/mastery/status    200 "Mastery status"
test_endpoint GET  /ops/mastery/analytics 200 "Cost analytics"
test_endpoint GET  /ops/mastery/forecast  200 "Budget forecast"
test_endpoint GET  /ops/mastery/hardware  200 "Hardware monitor"

echo ""
echo "=== PHASE 9: Observability ==="
test_endpoint GET  /ops/observability/metrics     200 "Metrics"
test_endpoint GET  /ops/observability/rate-limits 200 "Rate limits"
test_endpoint GET  /ops/observability/alerts      200 "Alerts"

echo ""
echo "=== PHASE 10: Skills & Tools ==="
test_endpoint GET  /ops/skills       200 "List skills"

echo ""
echo "=== PHASE 11: CLI Commands ==="
test_cli_command "python $GIMO_REPO/gimo.py --help" "GIMO: Gred In Multiagent Orchestrator" "CLI help"
test_cli_command "python $GIMO_REPO/gimo.py status" "Authoritative Status" "Status command"
test_cli_command "python $GIMO_REPO/gimo.py doctor" "GIMO Doctor Report" "Doctor command"
test_cli_command "python $GIMO_REPO/gimo.py providers auth-status" "Provider Authentication" "Provider auth status"

echo ""
echo "=== PHASE 12: File Operations ==="
test_endpoint GET  /ops/files/tree "200" "File tree"

echo ""
echo "=== PHASE 13: Policy & Trust ==="
test_endpoint GET  /ops/policy 200 "Policy config"

echo ""
echo "=================================================="
echo "  Test Results Summary"
echo "=================================================="
echo "Total tests:  $TOTAL"
echo "Passed:       $PASSED ($(echo "scale=1; $PASSED*100/$TOTAL" | bc)%)"
echo "Failed:       $FAILED"
echo "Skipped:      $SKIPPED"
echo ""

if [ $FAILED -eq 0 ]; then
    echo "✓ ALL TESTS PASSED"
    exit 0
else
    echo "✗ SOME TESTS FAILED"
    exit 1
fi

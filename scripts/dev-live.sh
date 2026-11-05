#!/usr/bin/env bash
# Temporary low-usage profile. The user's .env and key remain unchanged.
set -euo pipefail
export MOCK_MODELS=0 DEMO_MODE=1 SCHEDULER_ENABLED=0
export MAX_CANDIDATES=1 MAX_SAM_RETRIES=0 MAX_LIVE_MODEL_CALLS_PER_SCAN=6
export MAX_CLIPS_PER_CANDIDATE=2
export MAX_CLIP_SECONDS=5 SPARK_REASONING_EFFORT=minimal
export SPARK_MAX_COMPLETION_TOKENS="${SPARK_MAX_COMPLETION_TOKENS:-2048}"
exec bash "$(dirname "$0")/dev.sh"

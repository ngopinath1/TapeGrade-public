#!/usr/bin/env bash
# Explicit sample environment. No real model requests can run in this profile.
set -euo pipefail
export MOCK_MODELS=1 DEMO_MODE=1 SCHEDULER_ENABLED=0
export MAX_CANDIDATES=3 MAX_SAM_RETRIES=2 MAX_CLIP_SECONDS=30
exec bash "$(dirname "$0")/dev.sh"

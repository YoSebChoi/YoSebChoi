#!/bin/bash
# Claude Code 클라우드 세션 시작 시 agent-browser CLI를 설치한다.
# 컨테이너에 미리 설치된 Chromium을 쓰므로 `agent-browser install`(Chrome 다운로드)은 건너뛴다.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
command -v agent-browser >/dev/null 2>&1 || npm i -g agent-browser >/dev/null 2>&1

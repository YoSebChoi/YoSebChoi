#!/bin/bash
# Claude Code 클라우드 세션 시작 시 스킬이 쓰는 CLI를 설치한다.
# - agent-browser: 컨테이너에 미리 설치된 Chromium을 쓰므로 `agent-browser install`(Chrome 다운로드)은 건너뛴다.
# - graphify: .claude/settings.json의 PreToolUse 훅이 `graphify hook-guard`를 호출한다.
set -uo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
command -v agent-browser >/dev/null 2>&1 || npm i -g agent-browser >/dev/null 2>&1
command -v graphify >/dev/null 2>&1 || pip install -q graphifyy >/dev/null 2>&1
exit 0

#!/usr/bin/env bash
# 从本机技能库（唯一事实源）同步到本仓库并推送。
# 平时改 ~/.agents/skills/video-quote-image，改完跑这个，不要直接改仓库副本。
set -euo pipefail
SRC="$HOME/.agents/skills/video-quote-image/"
cd "$(dirname "$0")"
rsync -a --delete --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
      --exclude 'sync.sh' --exclude 'README.md' --exclude 'docs' "$SRC" .
git add -A
git diff --cached --quiet && { echo "没有变化"; exit 0; }
git commit -m "${1:-sync: 从本机技能库同步}"
git push

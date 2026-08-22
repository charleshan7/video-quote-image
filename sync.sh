#!/usr/bin/env bash
# 从本机 video-quote-image skill 的事实源同步到本仓库并推送。
# 可通过 VIDEO_QUOTE_IMAGE_SKILL_DIR 覆盖本机 skill 目录。
set -euo pipefail

DRY=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY=1
  shift
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="${VIDEO_QUOTE_IMAGE_SKILL_DIR:-$HOME/.agents/skills/video-quote-image}"

[ -f "$SRC/SKILL.md" ] || {
  echo "找不到 skill 事实源：$SRC/SKILL.md"
  echo "可设置 VIDEO_QUOTE_IMAGE_SKILL_DIR 指向 video-quote-image 目录。"
  exit 1
}

command -v rsync >/dev/null 2>&1 || {
  echo "找不到 rsync，无法同步 skill 目录。"
  exit 1
}

cd "$ROOT"

# 保留仓库专有的 README、版式示例和本同步脚本；其余 skill 内容以事实源为准。
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude 'README.md' \
  --exclude 'docs/' \
  --exclude 'sync.sh' \
  "$SRC/" "$ROOT/"

# 不把运行缓存、视频、图片成品或本地环境带入 skill 发布包。
find "$ROOT" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$ROOT" -type d -name '.venv' -prune -exec rm -rf {} +

git add -A
git diff --cached --quiet && {
  echo "没有变化"
  exit 0
}

if [ "$DRY" = 1 ]; then
  echo "── dry-run：以下是同步结果，未提交未推送 ──"
  git --no-pager diff --cached
  exit 0
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
  echo "当前分支是 $BRANCH，不是 main；为避免同步到错误分支，已停止。"
  exit 1
fi

git commit -m "${1:-sync: 更新 video-quote-image skill}"
git push -q origin "$BRANCH"

git fetch -q origin
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$BRANCH")" ]; then
  echo "push 后远端与本地不一致，未确认同步成功。"
  exit 1
fi

echo "已同步并推送（$BRANCH @ $(git rev-parse --short HEAD)）"

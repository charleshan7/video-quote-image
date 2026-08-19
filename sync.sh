#!/usr/bin/env bash
# 从本机技能库（唯一事实源）同步「金句长图」这一支到本仓库并推送。
#
# 2026-08-19 起，本机的金句长图 / 原生字幕拼图 / 轮播流水线 / 公众号长文
# 合并成了一个技能 video-to-social，事实源变成：
#     ~/.agents/skills/video-to-social/references/quote-image.md
# 本仓库只发布其中的金句长图这一支，所以这里是**选择性抽取**，不是整目录 rsync。
# 平时改事实源，改完跑这个；不要直接改仓库副本，会被下次同步覆盖。
set -euo pipefail
DRY=0; [ "${1:-}" = "--dry-run" ] && { DRY=1; shift; }
SRC="$HOME/.agents/skills/video-to-social"
cd "$(dirname "$0")"
[ -f "$SRC/references/quote-image.md" ] || { echo "找不到事实源：$SRC/references/quote-image.md"; exit 1; }

# ── SKILL.md ← references/quote-image.md
# 合并技能里它是一份 reference，独立发布需要补回 frontmatter，
# 并把指向合并技能内部其他文件的链接改写成本仓库读者能看懂的说法。
python3 - "$SRC" <<'PY'
import sys, pathlib
src = pathlib.Path(sys.argv[1])
t = (src / "references/quote-image.md").read_text()

t = t.replace("[native-subtitle.md](native-subtitle.md)", "`native-subtitle-quote-image`")
t = t.replace("[quote-image.md](quote-image.md)", "本文")
t = t.replace(
    "- `<SKILL_DIR>` 与 venv 的约定见 [SKILL.md](../SKILL.md)。",
    "- `<SKILL_DIR>` = 本 `SKILL.md` 所在目录的绝对路径，不要假设工作目录就是它。\n"
    "- 依赖在自带 venv：命令一律用 `\"<SKILL_DIR>/.venv/bin/python\"`。缺失时重建：\n\n"
    "  ```bash\n"
    "  uv venv --python 3.11 \"<SKILL_DIR>/.venv\" && uv pip install --python \"<SKILL_DIR>/.venv/bin/python\" -r \"<SKILL_DIR>/requirements.txt\"\n"
    "  ```")
t = t.replace("## 本产线专有约定", "## 路径与依赖")

fm = """---
name: video-quote-image
description: 把长视频（访谈、播客、演讲、纪录片）做成中文金句长图/语录图/字幕拼图时使用。本 skill 定义的是**编辑标准**——一套出几张、一张放几句、版式规格、翻译多轮校准——这套标准对"画面无硬字幕（文字按字幕轨重绘）"和"画面已烧录字幕（裁原帧）"两条渲染路径都适用。渲染路径：无硬字幕走本 skill 的脚本；有硬字幕走 native-subtitle-quote-image，但选句、版式、校准仍照本文执行。也用于修改既有金句长图的选句、时间点、配色、句数和画面数量。
---

"""
pathlib.Path("SKILL.md").write_text(fm + t)
PY

# ── 脚本与素材：只取金句这一支
mkdir -p scripts assets/brand
for f in locate_quotes.py render_quote_cards.py add_brand.py asr_crosscheck.py asr_elevenlabs.py; do
  cp "$SRC/scripts/$f" "scripts/$f"
done
rsync -a --delete "$SRC/assets/brand/" assets/brand/
cp "$SRC/requirements.txt" requirements.txt

git add -A
git diff --cached --quiet && { echo "没有变化"; exit 0; }
if [ "$DRY" = 1 ]; then
  echo "── dry-run：以下是抽取结果，未提交未推送 ──"
  git --no-pager diff --cached
  exit 0
fi
# 分支守卫：本脚本在**当前分支**上 commit。停在别的分支时（特性分支没切回来）
# 提交会落在那个分支上，而远端 main 纹丝不动。
# 姊妹仓库 skills-backup 就是这么静默丢了两次同步——push 报成功、远端 4 天没动。
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
  echo "⚠️  当前分支是 $BRANCH，不是 main。"
  echo "    本仓库的内容应该都在 main 上。请先处理该分支："
  echo "      git checkout main && git merge --ff-only $BRANCH"
  echo "    然后重跑本脚本。"
  exit 1
fi

git commit -m "${1:-sync: 从本机技能库同步}"
git push -q origin "$BRANCH"

# 推送后核实远端真的收到了，不靠 push 的退出码
git fetch -q origin
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$BRANCH")" ]; then
  echo "⚠️  push 后远端与本地不一致，未真正推上去。"
  exit 1
fi
echo "✅ 已同步并推送（$BRANCH @ $(git rev-parse --short HEAD)）"

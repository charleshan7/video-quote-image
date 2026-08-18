# video-quote-image

把**画面里没有烧录字幕**的长视频（访谈、播客、演讲、纪录片），做成可直接发小红书 / 公众号的**中文金句长图**。

画面来自原视频抽帧，文字由脚本按**字幕轨**渲染——这是它和 `native-subtitle-quote-image` 的根本区别，
后者只裁原画面里已有的硬字幕、一个字都不重绘。成品必须声明文字来源是字幕轨而非原画面。

![版式](docs/layout.jpg)

## 它解决什么

一集 56 分钟的播客，值得转发的可能就六七组话。手工做金句图的实际耗时不在排版，在这三件事：

1. **时间点对不上**。手填时间戳做出来的图，读者跳回原片会扑空。本 skill 强制回字幕文件里查真实时间点。
2. **压暗毁画面**。默认做法是给画面盖一层黑，七张连起来像一堵黑墙，绿植、灯光、衣服的质感全没了。
   这里默认**不压暗**，可读性交给文字的柔性阴影。
3. **翻译会走样**。压字数时最容易改掉主语和人称——把说话人在「学别人说话」的引语写成「我们」，
   意思会整个翻转。SKILL.md 里记了具体踩过的坑。

## 用法

```bash
# 1. 定位真实时间点：把人工挑好的 quotes.json 编译成 spec.json
.venv/bin/python scripts/locate_quotes.py SUBS.srt quotes.json -o spec.json

# 2. 渲染
.venv/bin/python scripts/render_quote_cards.py VIDEO --spec spec.json --out-dir output

# 3. 只给封面叠品牌标识（可选）
.venv/bin/python scripts/add_brand.py output/01_xxx.jpg --out output/01_xxx_带logo.jpg --spec spec.json
```

`quotes.json` 里的 `match` 必须**照抄字幕原文片段**，脚本靠它回字幕定位：

```json
{
  "meta": {"kicker": "SAM ALTMAN · INVEST LIKE THE BEST",
           "footer": "Invest Like The Best · 2026.07.28 · 56min"},
  "images": [
    {"title": "权力集中，才是真正可怕的事",
     "hero_time": 1085,
     "quotes": [
       {"match": "a lot of the safety talk is well-founded",
        "cn": "很多安全担忧有道理，也有很多是想集中权力",
        "en": "A lot of the safety talk is well-founded; a lot of it is people who want to concentrate power."}
     ]}
  ]
}
```

## 版式

1440×1920（3:4）。主画面占 36.2%，其余等分成字幕条，每条一句中文 + 一行英文 + 右下角时间码。

| 元素 | 位置 |
|---|---|
| kicker / 标题 / 出处 | 主画面左下，左边距 56 |
| 字幕条文字 | 左对齐，左边距 56，右下角时间码 |
| 品牌图标 | 主画面左上角 `(56, 56)` |
| `@` 字标 | footer 那行右端 + 28px，垂直居中对齐该行 |

品牌标识的位置是**相对锚点**，不写死像素——换素材、改 footer 文案、调 `--margin`，标识自己跟着挪。

## 目录

```
SKILL.md          技能定义（给 Claude Code / Codex 读的完整工作流与踩坑记录）
scripts/
  locate_quotes.py    回字幕定位真实时间点，quotes.json → spec.json
  render_quote_cards.py  抽帧、排版、渲染长图和总览图
  add_brand.py        叠品牌标识，位置用相对锚点
assets/brand/     品牌素材（双猫圆环图标 + 字标，透明底）
sync.sh           从本机技能库同步并推送
requirements.txt  Pillow + imageio-ffmpeg
```

## 依赖

macOS（字体路径写死在系统自带的 STHeiti / Hiragino / Arial Unicode），Python 3.11，ffmpeg。

```bash
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt
```

## 维护

本机的事实源是 `~/.agents/skills/video-quote-image`（Claude Code 和 Codex 都软链到那里）。
改完跑 `./sync.sh "说明"` 同步到本仓库并推送——**不要直接改仓库副本**，会被下次同步覆盖。

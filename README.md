# video-quote-image

把长视频（访谈、播客、演讲、纪录片）做成可直接发小红书 / 公众号的**中文金句长图**。

**这里定义的编辑标准对两条渲染路径都适用**：源片无硬字幕时文字按字幕轨重绘（走本 repo 的脚本），
源片已烧录字幕时裁原帧、一个字不重绘（走 `native-subtitle-quote-image`）——
但选几张、每张几句、版式规格、翻译校准，都照本 repo 的 `SKILL.md` 执行。

![版式](docs/layout.jpg)

## 核心不是脚本，是编辑标准

脚本谁都能写。这个 repo 真正的内容是 `SKILL.md` 里那三条标准——拿几十张废图换来的：

**一、选张与选句。** 一套 4–6 张；**一张放几句由论证结构决定，不套固定值**——断言+反转 3–4 句，
完整论证 5–6 句，递进链条 7–8 句，超过 8 句要么在凑数要么该拆成两张（8 句也是条高的物理上限）。
选句四条硬标准，外加一条收尾规则：**最后一句必须是全组最强的一句**，最强的落在中间就把后面全删。

**二、版式规格。** 条高 = (1920 − 695) ÷ 句数，5句→245px / 7句→175px / 8句→153px；
纯中文版行距全图统一 148px、主画面高由句数反推 `1920 − (句数−1)×148`（9 句时正好等于 16:9 满宽，
横幅双人镜头只能用这个数）。都是公式，不是每次现调。

**三、翻译多轮校准。** 自查 → 机械 diff → 换模型外部交叉校验，三轮缺一不可。
自查抓不出的是这两类：引语的人称（说话人在"学别人说话"，写成「我们」意思整个翻转）、
限定语和语气（删掉 `a lot of the safety talk is well-founded` 的前半句，就成了往人嘴里塞话）。

另外两条技术判断：**时间点必须回字幕文件查**，手填的跟画面对不上；**默认不压暗**，
七张压黑连起来像一堵黑墙，问题从来不是画面太亮而是文字对比度不够。

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

---
name: video-quote-image
description: 视频画面里没有烧录字幕、但要把它做成金句长图/语录图/字幕拼图时使用。适用于只有外挂字幕（SRT/VTT）或平台软字幕轨的访谈、播客、演讲、纪录片；也用于修改既有金句长图的选句、时间点、配色和画面数量。native-subtitle-quote-image 验出画面无硬字幕时改用本 Skill。
---

# 金句长图（画面无硬字幕）

画面来自原视频，**文字由脚本按字幕轨渲染**。成品必须标注文字来源是字幕轨而非原画面——这是和 `native-subtitle-quote-image` 的根本区别，不要混称"原生字幕"。

## 路径与依赖

- `<SKILL_DIR>` = 本 `SKILL.md` 所在目录的绝对路径，不要假设工作目录就是它。
- 依赖装在本 Skill 自带 venv：所有命令用 `"<SKILL_DIR>/.venv/bin/python"`。
  venv 缺失时重建：
  ```bash
  uv venv --python 3.11 "<SKILL_DIR>/.venv" && uv pip install --python "<SKILL_DIR>/.venv/bin/python" -r "<SKILL_DIR>/requirements.txt"
  ```

## 先做判定（顺序不能反）

1. **抽 3–5 帧看画面**，确认字幕**没有**烧录在画面里。若有硬字幕，停下改用 `native-subtitle-quote-image`（那条路的文字来自原帧，更可信）。
2. 确认拿得到字幕文件（SRT/VTT）。没有字幕轨就先转录，转录质量直接决定金句准确度。
3. 视频和字幕都要在本地。

## 工作流

1. 通读字幕逐字稿，按主题挑金句。每张图 4–5 句，同一张内要能连成一段完整表达。
2. 写 `quotes.json`。`match` 必须**照抄字幕原文片段**（用于回字幕定位，大小写无所谓，缩写和拼写要一致）：

   ```json
   {
     "meta": {"kicker": "DARIO AMODEI · THE CIRCUIT",
              "footer": "Bloomberg Originals · 2026.06.17 · 70min"},
     "images": [
       {"title": "红线画在哪里",
        "hero_time": 2320,
        "quotes": [
          {"match": "not worth democracies winning",
           "cn": "民主国家若靠做这些事赢，这个赢不值得",
           "en": "It's not worth democracies winning if democracies do those things."}
        ]}
     ]
   }
   ```

3. 定位真实时间点（**不要手填时间戳**，手填的跟画面对不上）：

   ```bash
   "<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/locate_quotes.py" \
     SUBS.srt quotes.json -o spec.json
   ```

4. 渲染：

   ```bash
   "<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/render_quote_cards.py" \
     VIDEO --spec spec.json --out-dir OUTPUT_DIR
   ```

5. **逐张看图**检查：文字完整不截断、同图内不重复、主画面标题没压到原片的人名条/台标、条与条之间无黑边。
6. 有问题只改 `quotes.json` 里对应项（换 `match`、加 `hero_time`），重跑 3–4 步。

## 选句与选帧

- 选句优先"能独立成立"的短句；需要上下文才成立的长句放弃。
- 一张图内**文字不能重复**，画面可以重复。
- `hero_time` 默认取该图第一句的时间点。原片在段落开头常打人名条，会和标题打架；发现压字就手动指定一个段落中段的时间点。
- 时长不足或分辨率低的源，仍输出 1440×1920，但**要说明这是放大尺寸**，不宣称提升清晰度。

## 压暗：默认不压

**默认 `--band-dim 0 --auto-dim 0`，画面保持原样，可读性靠文字的柔性阴影**
（`--shadow` 高斯半径默认 9、`--shadow-opacity` 0.78、`--shadow-spread` 3）。
硬描边 `--stroke` 默认关闭——等宽黑轮廓放大看像贴纸，阴影是向外衰减的暗场，
观感接近影视字幕。要更硬的边缘再开 `--stroke 2`。

不要一上来就压暗。整体压黑会把画面的颜色和层次全抹掉——绿植、衣服、灯光这些
让图有质感的东西都没了，七张连在一起像一堵黑墙。真正的问题从来不是"画面太亮"，
而是"文字对比度不够"，所以解法是给文字加描边，不是给画面盖黑布。

只有以下情况才动压暗参数：
- 素材整段是高调白背景（白墙演播室、PPT 录屏），描边也压不住 → `--band-dim 0.3` 起步
- 一套里只有一两条特别亮 → `--auto-dim 95`，只对超过阈值的条按需压，暗的不动

## 可调样式

`--aspect`（默认 3:4）、`--width`、`--hero-fraction`、`--cn-size`、`--en-size`、
`--title-size`、`--stroke`、`--band-focus`、`--hero-focus`。跑 `--help` 看默认值。
输出目录非空会直接报错，不覆盖已有成品。

## 品牌标识（固定位置，别每次重新商量）

图标和字标的位置是**定死的规则**，不是每张图临时决定的构图。位置用相对参照物算，
不写死像素——换素材、改 footer 文案、调 `--margin`/`--hero-fraction`，标识自己跟着挪。

| 元素 | 锚点 | 样式 |
|---|---|---|
| 双猫圆环图标 | 主画面左上角 `(margin, margin)`，和标题/字幕同一条左边距 | 高 96px，黑墨 + 白色柔光垫底 |
| `@飞飞豆芽` 字标 | footer 那行（`…· 2026.07.28 · 56min`）**右端 + 28px**，垂直居中对齐该行 | 墨迹高 22px，白色，无垫底 |

```bash
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/add_brand.py" \
  OUTPUT_DIR/01_xxx.jpg --out OUTPUT_DIR/01_xxx_带logo.jpg --spec spec.json
```

素材唯一源 `~/Developer/ffdy-brand/`（`cat-circle.webp` + `wordmark.webp`），
脚本默认就读这里，跨项目不用再找。

几条踩过的坑，改参数前先看：

- **两个 logo 都是「黑线稿 + 白实底」**。整体涂色会连白底一起涂，猫身和线条糊成一坨，
  远看就是一块白斑。必须按墨色深浅转 alpha（`line_alpha()`），只有黑线上色、白底透出照片。
- **黑墨必须垫底**。主画面左上角亮度只有 76–107，纯黑线稿会沉进背景。垫底用**柔光**
  （`--halo`，向外衰减）而不是白圆片——圆片边界硬，看着像贴纸。
- **字标用白色**。主画面中下部亮度 39–130，黑字在那儿会消失；这套版式所有文字本来也是白的。
- 只叠**封面那一张**，其余图不叠，避免整组重复。

要改就改 `--icon-h`/`--halo`/`--word-h`/`--word-gap`，位置锚点不要改成绝对坐标。

## 交付

给出输出目录、总览图、`spec.json`（含每句时间戳，便于回原片核对），并**明确声明文字来自字幕轨、非原画面**。未逐张检查过的图不得报告为完成。

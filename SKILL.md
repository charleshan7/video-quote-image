---
name: video-quote-image
description: 把访谈、播客、演讲或纪录片制作成可核验的中文或双语金句长图及小红书发布包；适用于需要真实视频帧、来源时间码、翻译校准、人物核验和交付审计的任务。
---

# Video Quote Image

目标是交付一套能回到原片核对的金句长图，而不只是“成功生成图片”。真实帧、原文、时间码、人物身份和最终版本必须属于同一来源版本。

## 先选择交付状态

- `draft`：可供内部看方向；允许视觉告警和未完成审计，但必须标明是草稿。
- `reviewed`：所有逐句校准、人物、选帧、发布包和版本哈希完整；允许明确记录的非关键限制。
- `final`：在 reviewed 基础上，必须有异构 ASR 第二来源且所有风险项已收敛。

不要把较低状态描述成最终交付。`scripts/preflight.py` 的退出码是交付门禁，但仍需人工逐张查看原尺寸图片。

## 按任务读取参考

- 选题、句数、核心句和人物角色：读 [references/editorial.md](references/editorial.md)。
- 版式、字体、烧录字幕处理、真实帧和品牌：读 [references/layout.md](references/layout.md)。
- 英文原文与中文四轮校准：读 [references/calibration.md](references/calibration.md)。
- 人物介绍、小红书文案和轮播：读 [references/publishing.md](references/publishing.md)。
- 目录、JSON 字段、状态门禁和打包：读 [references/artifact_contracts.md](references/artifact_contracts.md)。
- 下载证据边界：读 [references/download_policy.md](references/download_policy.md)。
- 纯中文版式 B 仍是实验规格，仅在用户明确要求时读 [references/format_b.md](references/format_b.md)。

## 不可妥协的事实约束

1. 使用完整、可逐帧读取且同时含音视频流的直接来源；预览、缩略图和剪辑版不能冒充原片。
2. `time` 是字幕来源时间，`frame_time` 是独立选择的真实画面时间。不得为了避免重复画面而改写来源时间。
3. 英文 `source_en` 必须回溯到字幕或异构 ASR；中文不得加入来源中没有的事实、数量、主语或语气。
4. 头图和条带只能使用真实帧。禁止 AI 补脸、换脸、表情迁移或生成替代画面。
5. 字体缺失、中文字形缺失、文字溢出、原烧录字幕处理不明或证据文件不一致时必须停止 reviewed/final。
6. 每版使用独立目录；不要覆盖旧版，也不要把未带标和已带标图片混在一起。
7. 云端 ASR 会上传音频。只有用户允许且命令显式带 `--allow-cloud` 时才能使用；涉密素材使用本地 ASR。

## 标准执行路径

以下命令里的 `<SKILL_DIR>` 是本目录绝对路径。优先使用 Skill 自带 venv。

### 1. 环境检查

```bash
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/doctor.py"
```

缺 venv 时：

```bash
uv venv --python 3.11 "<SKILL_DIR>/.venv"
uv pip install --python "<SKILL_DIR>/.venv/bin/python" -r "<SKILL_DIR>/requirements.txt"
```

需要本地 Whisper 时另装 `requirements-asr.txt`；需要由 venv 提供 yt-dlp 时装 `requirements-tools.txt`。`ffprobe` 和系统字体仍需由宿主环境提供。

### 2. 下载并保存来源证据

```bash
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/download_source.py" URL \
  --out-dir PROJECT/source
```

脚本证明的是“yt-dlp 在当前账号、地区和 Cookie 可见范围内选择的最佳格式”，不是所有访问条件下的绝对最高版本。确认字幕与视频属于同一版本后，把字幕保存为 `audit/source_subs.srt` 或 `.vtt`。

### 3. 选句并定位

先写带稳定 `image.id` 和 `quote_id` 的 `audit/quotes.json`，再定位：

```bash
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/locate_quotes.py" \
  audit/source_subs.srt audit/quotes.json -o audit/spec.json
```

定位失败时不会写出残缺 spec。同一 cue 内的多条引用可以共享来源时间；之后单独选择各自 `frame_time`。

### 4. 校准和选帧

按 calibration reference 生成四轮逐句 JSON。每句至少比较 5 个真实候选帧；每张头图至少比较 8 个宽窗口候选，并把选择写入 `audit/frame_audit.json` 和 spec。

### 5. 渲染

先检查源片是否有烧录字幕。没有时使用 `verified-absent`；有时通过安全裁切去除后使用 `cropped` 并给出实际裁切比例。不能证明已隐藏时保持 `unknown`，该状态会阻断 reviewed/final。

```bash
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/render_quote_cards.py" VIDEO \
  --spec audit/spec.json --out-dir images --render-json audit/render.json \
  --source-subtitle-policy verified-absent \
  --aspect 3:4 --width 1440 --hero-fraction 0.362 \
  --hero-focus 0.0 --band-focus 0.34 --cn-size 52 --en-size 28
```

如果字体不在自动发现路径，显式传 `--cjk-bold-font`、`--cjk-regular-font` 和 `--latin-font`。不得接受默认方框字或不明字体替代。

### 6. 品牌、发布包与交付

把品牌图放在独立目录：

```bash
mkdir -p branded audit/brand
for f in images/0*.jpg; do
  name="$(basename "$f")"
  "<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/add_brand.py" "$f" \
    --out "branded/$name" --spec audit/spec.json --render audit/render.json \
    --metadata "audit/brand/${name%.jpg}.json"
done
```

逐张查看 1440×1920 原图，确认人物、眼睛、构图、原字幕隐藏、文字、时间码和品牌位置。随后完成 `xiaohongshu_package.md`，构建 manifest，创建 ZIP，再运行 preflight：

```bash
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/build_release_manifest.py" \
  --root PROJECT --status final --version v1 --zip ../release-v1.zip

"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/preflight.py" \
  --root PROJECT --video source/source.mkv --status final --zip ../release-v1.zip
```

只有 preflight 退出 0、ZIP 成员哈希与 manifest 一致、且原尺寸人工检查完成，才能报告为 reviewed/final。

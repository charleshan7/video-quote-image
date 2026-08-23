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
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/doctor.py" --mode download
```

缺 venv 时：

```bash
uv venv --python 3.11 "<SKILL_DIR>/.venv"
uv pip install --python "<SKILL_DIR>/.venv/bin/python" -r "<SKILL_DIR>/requirements-tools.txt"
```

只处理本地视频时用 `--mode render`；需要云端 ASR 时另跑 `--mode cloud-asr`。本地 Whisper 另装 `requirements-asr.txt`；维护 Skill 和运行校验时安装 `requirements-dev.txt`。`ffprobe` 和系统字体仍需由宿主环境提供。

### 2. 下载并保存来源证据

```bash
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/download_source.py" URL \
  --out-dir PROJECT/source
```

脚本使用 `--ignore-config`，避免宿主机 yt-dlp 全局配置静默改变结果。它证明的是“当前访问条件下可见的最佳格式”，不是所有账号和地区下的绝对最高版本。后续命令中的 `VIDEO` 必须使用 `source_download.json.media_path` 指向的实际文件；不要假定扩展名一定是 MKV。确认字幕与视频属于同一版本后，把字幕保存为 `audit/source_subs.srt` 或 `.vtt`。

### 3. 选句并定位

先写带稳定 `image.id` 和 `quote_id` 的 `audit/quotes.json`，再定位：

```bash
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/locate_quotes.py" \
  audit/source_subs.srt audit/quotes.json -o audit/spec.json
```

定位失败或同一句存在多个候选位置时不会写出 spec。歧义时在 quotes 中显式填写 `occurrence`、`after_time` 或 `before_time`。同一 cue 内的多条引用可以共享来源时间；之后单独选择各自 `frame_time`。

### 4. 校准和选帧

按 calibration reference 生成四轮逐句 JSON。`stop` 会阻断交付；`revise` 必须真实更新 spec。ASR 完成报告必须绑定当前视频、字幕、引擎、模型、架构家族和逐段哈希。

生成真实候选帧证据：

```bash
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/extract_frame_candidates.py" VIDEO \
  --root PROJECT --spec audit/spec.json --reviewer "REVIEWER"
```

逐张检查候选图，填写 `chosen_reason`，并让最终时间同时写入 `frame_audit.json` 和 spec。独立选择后的最佳帧允许恰好等于来源时间；门禁检查的是选择证据，不是强制时间不同。

### 5. 渲染

先生成烧录字幕抽样证据。没有时使用 `verified-absent`；有时通过安全裁切去除后使用 `cropped` 并给出实际裁切比例：

```bash
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/extract_subtitle_audit.py" VIDEO \
  --root PROJECT --policy verified-absent --reviewer "REVIEWER"
```

至少检查三组原帧和处理帧，把 `decision=review-required` 改成真实结论。`cropped` 时抽样命令和渲染必须使用相同的 `--crop-bottom/--source-crop-bottom`。没有结构化证据会阻断 reviewed/final。

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

逐张查看 1440×1920 原图，确认人物、眼睛、构图、原字幕隐藏、文字、时间码和品牌位置。随后完成 `xiaohongshu_package.md`，用确定性打包脚本一次性构建 manifest、精确成员 ZIP 和外部哈希证明，再运行 preflight：

```bash
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/package_release.py" \
  --root PROJECT --status final --version v1 --zip ../release-v1.zip \
  --branding required

"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/preflight.py" \
  --root PROJECT --video VIDEO --status final --zip ../release-v1.zip
```

不需要品牌时必须显式使用 `--branding none`，且不得留下 branded/ 或 audit/brand 文件。ZIP 不允许额外、重复、加密、符号链接或未登记成员。只有 preflight 退出 0、ZIP/manifest/attestation 一致、且原尺寸人工检查完成，才能报告为 reviewed/final。

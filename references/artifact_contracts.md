# 产物契约与状态门禁

推荐目录：

```text
PROJECT/
  source/source.mkv
  source/source_download.json
  audit/quotes.json
  audit/spec.json
  audit/source_subs.srt
  audit/selection_audit.json
  audit/translation_audit.json
  audit/review_asr_xcheck.json
  audit/round1_self_check.json
  audit/round2_mechanical_diff.json
  audit/round3_adjudication.json
  audit/people.json
  audit/frame_audit.json
  audit/render.json
  audit/red_team.json          # 风险触发时
  audit/release_manifest.json
  images/
  branded/
  xiaohongshu_package.md
```

JSON 结构以 `schemas/*.schema.json` 和 `templates/` 为准。稳定键为 `image.id` 和 `quote_id`；标题、文件名和数组位置不能代替 ID。

## draft

需要直接来源、字幕、quotes、spec、渲染图片和 render 证据。允许渲染 warning，但必须明确标记草稿；输出状态应为 `DRAFT_ALLOWED`，不能显示 final。

## reviewed/final

除 draft 产物外，还需要 selection、四轮 translation、ASR JSON、people、frame audit、发布包、manifest 和 ZIP。风险标签触发时必须有逐句 red-team 决策。

Manifest 对所有关键 artifact 和图片做 SHA-256。preflight 会检查当前文件哈希、render/spec/video 绑定、选帧候选、ZIP 安全路径及 ZIP 内成员哈希。ZIP 路径必须同时与 CLI 和 manifest 一致。

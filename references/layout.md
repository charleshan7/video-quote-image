# 版式、真实帧与品牌

## 默认版式 A

画布 1440×1920，主画面比例 0.362。剩余高度按实际引用数等分；不要使用全局固定 `--bands` 截断引用。

中文默认 52px、英文 28px、时间码 24px。渲染器的 overflow warning 会阻断 reviewed/final；应换句、增加条带高度或显式调整版式，不得静默截断。

## 字体

定稿字重是**思源黑体 SC Heavy**（`~/Library/Fonts/SourceHanSansSC-Heavy.otf`），
候选表首位，不用传参数。选它的理由：简体字面、字重足够压住画面，
七条排下来不糊；Bold 更透气但首图冲击力不足，得意黑自带倾斜、只适合标题。

候选顺序：思源黑 Heavy → Noto CJK Black/Bold → Linux 系统 Noto → macOS 华文黑体 → Windows 雅黑。
自动发现失败时显式传 `--cjk-bold-font`，或设环境变量 `VIDEO_QUOTE_IMAGE_CJK_BOLD_FONT`。

**ttc 字体集合必须指定 face 序号**，写成 `路径::序号`。
`STHeiti Medium.ttc` 的 face 0 是 Heiti TC（繁体字面），简体在 face 1——
按 0 取等于用繁体字面渲简体文案，「直真具者每骨」这些字会不对味。
候选表里已写成 `::1`，自己传路径时也要带。

实际路径和文件哈希都会写进 `render.json`；禁止静默回退到 Pillow 默认字体。

## 烧录字幕

渲染前使用 `extract_subtitle_audit.py` 保存至少三个时刻的原帧和处理帧，并逐张记录结论：

- `verified-absent`：确认原画面没有烧录文字。
- `cropped`：原字幕位于底部，使用 `--source-crop-bottom` 从所有真实帧中裁掉该区域并在原尺寸复核。
- `unknown`：尚未确认；只能用于 draft。

裁切后仍出现原字幕，或字幕位于不可安全裁掉的位置时，应更换视觉方案或停止，不要让原字幕和重绘文字叠加。

## 真实帧

`time` 记录引用来源，`frame_time` 记录画面。每句围绕来源时间至少比较 5 帧；头图在相关主题宽窗口至少比较 8 帧。使用 `extract_frame_candidates.py` 保存候选图片、时间和哈希；人工填写选择理由并让最终选择与 spec 一致。独立选择后的数值可以等于 `time`。

## 品牌

默认使用版本库内 `assets/brand`，确保不同机器输出一致。只有用户明确指定其他品牌资产时才用 `--logo-dir`。默认交付模式是 `branding=required`：品牌图必须写入独立 `branded/`，并为每张输出包含源图、输出、字体、render 和品牌资产哈希的证据 JSON。只有显式 `branding=none` 才能无品牌交付。

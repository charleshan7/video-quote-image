# 版式 B · 纯中文压缩流

此版式当前不是默认交付路径。`compose_overlay.py` 不在本技能中，`render_quote_cards.py` 也没有 `--hero-lines` 参数，因此不要把下面的草案命令当作可执行流程。

若确实需要纯中文居中效果，可用已验证的居中细条参数：

```bash
--align center --text-pos center --no-en --no-timestamp --no-rule --no-hero-text \
--hero-fraction 0.45 --band-focus 0.88 --cn-size 50
```

| 项 | 值 |
|---|---|
| 行距 | 全图统一 148px |
| 中文 | 54px 居中 |
| 去掉 | 英文、时间码、分隔线、标题、落款 |
| 主画面高 | `1920 − (句数−1) × 148`，由句数反推 |

9 句时 hero = 736px，正好等于原片 16:9 满宽；横幅两人镜头使用这个数，避免竖裁。主画面叠 3 句时必须使用单人特写，两人全景不适用。默认仍使用版式 A，因为它保留英文原文和时间码，便于核对。

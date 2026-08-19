#!/usr/bin/env python3
"""ElevenLabs Scribe 的 ASR 适配器，输出对齐 asr_crosscheck.py 期望的 {stem}.txt。

当第二家引擎用。和 whisper 的价值不在谁更准，在**误差不相关**——
whisper 的错来自"语言模型按概率补词"，Scribe 训练数据和架构都不同，
同一处未必犯同样的错。拿两个同源模型互校基本是白跑。

    asr_crosscheck.py VIDEO --spec spec.json --subs SUBS.srt --out-dir x \
      --asr-cmd 'whisper-cli -m MODEL -f {wav} -l en -otxt -of {stem} -np' \
      --verify-cmd 'python3 <SKILL_DIR>/scripts/asr_elevenlabs.py --wav {wav} --stem {stem}'

计费：约 67 字符/分钟音频（2026-08 实测），免费档 10000 字符 ≈ 2.5 小时音频/月。
超额计费默认关闭，额度用尽是报错不是扣钱。

⚠️ 云端 API，**音频会离开本机**。素材涉密时只能用本地 whisper。
"""
import argparse, json, os, subprocess, sys
from pathlib import Path

API = "https://api.elevenlabs.io/v1/speech-to-text"
SUB = "https://api.elevenlabs.io/v1/user/subscription"
ENV_CHAIN = ["~/.elevenlabs.env", "~/Developer/video-use/.env"]


def load_key(env_file):
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"]
    for cand in ([env_file] if env_file else []) + ENV_CHAIN:
        p = Path(cand).expanduser()
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("ELEVENLABS_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("找不到 ELEVENLABS_API_KEY：设环境变量，或用 --env-file 指定 .env")


def quota(key):
    r = subprocess.run(["curl", "-sS", "--max-time", "30", "-H", f"xi-api-key: {key}", SUB],
                       capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
        return d["character_count"], d["character_limit"]
    except Exception:
        return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wav", required=True)
    ap.add_argument("--stem", required=True, help="输出写到 {stem}.txt")
    ap.add_argument("--model", default="scribe_v1")
    ap.add_argument("--lang", default="", help="语言码如 eng；留空让它自己判断")
    ap.add_argument("--env-file", help="含 ELEVENLABS_API_KEY 的 .env")
    ap.add_argument("--quota", action="store_true", help="只查额度，不识别")
    a = ap.parse_args()

    key = load_key(a.env_file)
    if a.quota:
        used, lim = quota(key)
        print(f"{used}/{lim} 字符，剩 {lim - used} ≈ {(lim - used) / 67:.0f} 分钟音频"
              if used is not None else "查不到额度")
        return

    cmd = ["curl", "-sS", "--max-time", "300", "-X", "POST", API,
           "-H", f"xi-api-key: {key}",
           "-F", f"file=@{a.wav}", "-F", f"model_id={a.model}"]
    if a.lang:
        cmd += ["-F", f"language_code={a.lang}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"请求失败：{r.stderr.strip()[:200]}")
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.exit(f"返回不是 JSON（前 200 字符）：{r.stdout[:200]}")
    if "text" not in d:
        used, lim = quota(key)
        extra = f"（当前额度 {used}/{lim}）" if used is not None else ""
        sys.exit(f"识别失败{extra}：{json.dumps(d, ensure_ascii=False)[:300]}")

    out = Path(f"{a.stem}.txt")
    out.write_text(d["text"], encoding="utf-8")
    print(f"{out}  {d.get('audio_duration_secs', '?')}s  {d.get('language_code', '?')}")


if __name__ == "__main__":
    main()

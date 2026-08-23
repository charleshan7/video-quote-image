#!/usr/bin/env python3
"""ElevenLabs Scribe 的 ASR 适配器，输出对齐 asr_crosscheck.py 期望的 {stem}.txt。

当第二家引擎用。和 whisper 的价值不在谁更准，在**误差不相关**——
whisper 的错来自"语言模型按概率补词"，Scribe 训练数据和架构都不同，
同一处未必犯同样的错。拿两个同源模型互校基本是白跑。

    asr_crosscheck.py VIDEO --spec spec.json --subs SUBS.srt --out-dir x \
      --asr-cmd 'whisper-cli -m MODEL -f {wav} -l en -otxt -of {stem} -np' \
      --verify-cmd 'python3 <SKILL_DIR>/scripts/asr_elevenlabs.py --wav {wav} --stem {stem}'

⚠️ 云端 API，**音频会离开本机**。素材涉密时只能用本地 whisper。
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.elevenlabs.io/v1/speech-to-text"
SUB = "https://api.elevenlabs.io/v1/user/subscription"


def load_key(env_file):
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"]
    for cand in ([env_file] if env_file else []):
        p = Path(cand).expanduser()
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("ELEVENLABS_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("找不到 ELEVENLABS_API_KEY：设环境变量，或显式用 --env-file 指定 .env")


def quota(key):
    r = subprocess.run(["curl", "-sS", "--max-time", "30", "-H", f"xi-api-key: {key}", SUB],
                       capture_output=True, text=True, check=False)
    try:
        d = json.loads(r.stdout)
        return d["character_count"], d["character_limit"]
    except Exception:  # noqa: BLE001 - subscription responses vary by account tier
        return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wav", required=True)
    ap.add_argument("--stem", required=True, help="输出写到 {stem}.txt")
    ap.add_argument("--model", default="scribe_v2")
    ap.add_argument("--lang", default="", help="语言码如 eng；留空让它自己判断")
    ap.add_argument("--env-file", help="含 ELEVENLABS_API_KEY 的 .env")
    ap.add_argument("--quota", action="store_true", help="只查额度，不识别")
    ap.add_argument("--allow-cloud", action="store_true",
                    help="确认允许把该音频发送到 ElevenLabs；识别时必须显式提供")
    a = ap.parse_args()

    key = load_key(a.env_file)
    if a.quota:
        used, lim = quota(key)
        print(f"订阅接口返回 character_count={used}, character_limit={lim}；"
              "该字段不能换算为剩余 STT 分钟，请以 ElevenLabs Analytics/账单为准。"
              if used is not None else "查不到订阅额度")
        return
    if not a.allow_cloud:
        raise SystemExit("云端识别需要显式添加 --allow-cloud；音频会离开本机")

    cmd = ["curl", "-sS", "--fail-with-body", "--max-time", "300", "-X", "POST", API,
           "-H", f"xi-api-key: {key}",
           "-F", f"file=@{a.wav}", "-F", f"model_id={a.model}"]
    if a.lang:
        cmd += ["-F", f"language_code={a.lang}"]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
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
    digest = hashlib.sha256()
    with Path(a.wav).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    out.with_suffix(".meta.json").write_text(json.dumps({
        "provider": "elevenlabs", "model": a.model, "language_requested": a.lang or None,
        "language_detected": d.get("language_code"), "wav_sha256": digest.hexdigest(),
        "requested_at": datetime.now(timezone.utc).isoformat(), "status": "complete",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{out}  {d.get('audio_duration_secs', '?')}s  {d.get('language_code', '?')}")


if __name__ == "__main__":
    main()

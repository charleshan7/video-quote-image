#!/usr/bin/env python3
"""Download the highest-quality directly available video source and audit it.

The script intentionally uses yt-dlp's best video + best audio selector rather
than a convenience preview format. It writes source_download.json next to the
media file so the delivery preflight can prove what was downloaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from media_tools import ffprobe_exe


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def run_json(cmd: list[str]) -> dict:
    return json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('url')
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--basename', default='source')
    ap.add_argument('--manifest', default='source_download.json')
    args=ap.parse_args()
    out=Path(args.out_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    existing=[p for p in out.glob(args.basename+'.*') if p.is_file()]
    if existing or (out/args.manifest).exists():
        raise SystemExit(f'output already contains source artifacts; use a new directory: {out}')
    template=str(out / (args.basename + '.%(ext)s'))
    selector='bestvideo*+bestaudio/best'
    cmd=['yt-dlp','--ignore-config','--no-playlist','--format',selector,'--format-sort','res,fps,vcodec,acodec,abr','--merge-output-format','mkv','--write-info-json','--no-write-playlist-metafiles','--output',template,'--print','after_move:filepath',args.url]
    try:
        result=subprocess.run(cmd, check=True, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise SystemExit('yt-dlp is not installed; run scripts/doctor.py') from exc
    except subprocess.CalledProcessError as exc:
        detail=(exc.stderr or exc.stdout or '').strip()[-1200:]
        raise SystemExit(f'yt-dlp download failed:\n{detail}') from exc
    paths=[Path(line.strip()) for line in result.stdout.splitlines() if line.strip() and Path(line.strip()).exists()]
    media=next((p for p in reversed(paths) if p.suffix.lower() in {'.mkv','.mp4','.webm','.mov'}), None)
    if media is None:
        candidates=sorted(out.glob(args.basename+'.*'))
        media=next((p for p in candidates if p.suffix.lower() in {'.mkv','.mp4','.webm','.mov'}), None)
    if media is None: raise SystemExit('yt-dlp completed but merged media file was not found')
    probe=run_json([ffprobe_exe(),'-v','error','-show_entries','format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,bit_rate,avg_frame_rate,sample_rate,channels','-of','json',str(media)])
    streams=probe.get('streams',[])
    info_path=out/(args.basename+'.info.json')
    info={}
    if info_path.exists():
        info=json.loads(info_path.read_text(encoding='utf-8'))
    video=[s for s in streams if s.get('codec_type')=='video']
    audio=[s for s in streams if s.get('codec_type')=='audio']
    if not video or not audio:
        raise SystemExit('downloaded media does not contain both video and audio streams')
    version=subprocess.run(['yt-dlp','--version'],capture_output=True,text=True,check=True).stdout.strip()
    requested=info.get('requested_formats') or []
    manifest={
        'source_url':args.url,
        'webpage_url':info.get('webpage_url') or info.get('original_url') or args.url,
        'extractor':info.get('extractor'),
        'source_id':info.get('id'),
        'title':info.get('title'),
        'upload_date':info.get('upload_date'),
        'downloaded_at':datetime.now(timezone.utc).isoformat(),
        'yt_dlp_version':version,
        'download_mode':'direct',
        'format_selector':selector,
        'quality_scope':'best_visible_to_yt_dlp',
        'best_visible_to_yt_dlp':bool(info and (requested or info.get('format_id'))),
        'quality_evidence':'yt-dlp selector plus requested_formats from info JSON',
        'configuration_scope':'--ignore-config; only options recorded by this script were applied',
        'media_path':str(media.relative_to(out)),
        'container':media.suffix.lstrip('.'),
        'file_sha256':sha256(media),
        'duration_seconds':float(probe.get('format',{}).get('duration') or 0),
        'file_size_bytes':media.stat().st_size,
        'format_size_bytes':int(float(probe.get('format',{}).get('size') or media.stat().st_size)),
        'format_bitrate':probe.get('format',{}).get('bit_rate'),
        'video_streams':video,
        'audio_streams':audio,
        'yt_dlp_format_id':info.get('format_id'),
        'yt_dlp_requested_formats':info.get('requested_formats'),
        'yt_dlp_ext':info.get('ext'),
        'yt_dlp_protocol':info.get('protocol'),
        'info_json_path':str(info_path.relative_to(out)) if info_path.exists() else None,
        'info_json_sha256':sha256(info_path) if info_path.exists() else None,
    }
    manifest_path=out/args.manifest
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=='__main__': main()

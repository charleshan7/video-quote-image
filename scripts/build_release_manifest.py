#!/usr/bin/env python3
"""Build the release integration manifest before packaging a quote-image delivery."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',required=True)
    ap.add_argument('--status',choices=['reviewed','final'],required=True)
    ap.add_argument('--version',required=True)
    ap.add_argument('--zip',default='../release.zip')
    ap.add_argument('--spec',default='audit/spec.json')
    ap.add_argument('--output',default='audit/release_manifest.json')
    args=ap.parse_args()
    root=Path(args.root).resolve()
    spec=json.loads((root/args.spec).read_text(encoding='utf-8'))
    images=sorted((root/'images').glob('0*.jpg'))
    artifact_paths=[
        'source_download.json',args.spec,'audit/quotes.json','audit/selection_audit.json','audit/translation_audit.json',
        'audit/source_subs.srt','audit/frame_audit.json','audit/render.json','xiaohongshu_package.md'
    ]
    artifact_hashes={}
    for rel in artifact_paths:
        p=root/rel
        if not p.exists(): raise SystemExit(f'missing artifact: {rel}')
        artifact_hashes[rel]=sha256(p)
    for p in images:
        artifact_hashes[str(p.relative_to(root))]=sha256(p)
    branded=sorted((root/'branded').glob('0*.jpg'))
    if branded:
        for p in branded:
            artifact_hashes[str(p.relative_to(root))]=sha256(p)
    quote_count=sum(len(i.get('quotes',[])) for i in spec.get('images',[]))
    manifest={
        'version':args.version,
        'status':args.status,
        'image_count':len(images),
        'quote_count':quote_count,
        'artifact_hashes':artifact_hashes,
        'release_zip':args.zip,
        'risk_flags':(spec.get('meta') or {}).get('risk_flags',[]),
    }
    out=root/args.output
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=='__main__': main()

# Full Workflow Review

## Recommended production pipeline

The workflow should be treated as a gated state machine rather than a loose checklist. Each phase has an input contract, a required evidence artifact, and a stop condition. Do not enter the next phase when the current gate is red.

| Phase | Input | Required output | Hard stop |
|---|---|---|---|
| 0. Request and risk intake | User request, source URL, requested format | `project_manifest.json` with source URL, intended status, privacy/usage notes and risk flags | Source or output goal is ambiguous; ask instead of assuming. |
| 1. Material gate | Original source URL and downloaded media | `source_download.json`, `source_probe.json`, complete highest-quality direct source, merged audio/video, primary subtitle source and version identity | Best-quality selector not used, duration mismatch, missing stream, truncated download, subtitle/media version mismatch or no auditable source. |
| 2. Quote map | Primary SRT/VTT, transcript context | `quotes.json`, `selection_audit.json`, `spec.json` with located `time` | Hand-entered time, unsupported half-sentence, fixed-count padding, missing core quote, repeated information or context facts outside the source span. |
| 3. Four-round calibration | Quote map and audio | `translation_audit.json` plus four quote-level artifacts | Any missing round, non-completed status, missing artifact, incomplete row, unresolved high-risk discrepancy or count mismatch. |
| 4. Frame audit | Video, `spec.json` | `frame_audit.json`, selected `frame_time`, at least five quote candidates and at least eight wide-window hero candidates per image | Fewer than five quote candidates, fewer than eight hero candidates, `time == frame_time`, hero not interviewer/speaker, closed eyes, cut transition or AI-generated replacement. |
| 5. Render and visual QA | Versioned spec, fonts, renderer | New output directory, `render.json`, unbranded images, contact sheet, original-size visual notes | Any renderer warning, overflow, wrong dimension, font fallback, unreadable text, burned-in subtitle leakage or version overwrite. |
| 6. Brand and package | Clean output directory and brand assets | Separate `branded/`, `people.json`, `xiaohongshu_package.md` | Missing or duplicated brand mark, person/source mismatch, package/image version mismatch or missing traceability IDs. |
| 7. Release integration | All previous artifacts | `release_manifest.json` with hashes, `preflight_report.*`, verified ZIP | Any count/hash/version mismatch, missing required artifact or corrupt archive. |
| 8. Conditional red team | `spec.meta.risk_flags`, four-round evidence | `red_team.json` with one challenge row per quote | Triggered risk not explicitly flagged, row missing, unresolved `revise/stop`, or claim cannot be bounded to source evidence. |

## Key optimizations

### Separate source truth from derived truth

Use `source_subs.srt` as the primary authority for the displayed English quote and timestamp. Keep second ASR outputs in a separate `asr-xcheck` directory. Never make an exact-match validator pass by replacing the primary subtitle source with a second ASR transcript.

### Make the quote ID immutable

Assign each quote an ID such as `03-05` at selection time. Carry that ID unchanged through `quotes.json`, `selection_audit.json`, all four calibration artifacts, `frame_audit.json`, `spec.json`, rendered filenames, carousel copy and release manifest. If a quote is replaced, create a new ID or a recorded supersession; do not silently reuse the old one.

### Compute risk instead of relying only on manual labels

The creator may add `spec.meta.risk_flags`, but the validator should also scan source text and quote metadata for politics, war, religion, medical, legal, finance, minors, numbers, proper nouns and strong claims. A detected trigger must either be explicitly acknowledged or block delivery. This prevents “forgot to label the risk” failures.

### Treat warnings as data

Renderer overflow and font fallback messages must be captured in `render.json`, not left only in terminal output. The release gate must fail when the warnings array is non-empty. A human-readable report may explain the issue, but it must not override the machine gate.

### Add the release integration layer

The fifth layer is not another translation round. It checks the graph of derived artifacts: source subtitle → quote map → spec → frame audit → render → brand → publication package → ZIP. Store SHA-256 hashes and counts so a later edit cannot silently leave the image set and audit files on different versions.

### Use a conditional red-team lane

Do not make every low-risk interview pay the cost of a full red team. Trigger it for politically or socially sensitive content, numbers, proper nouns, legal/medical/financial claims, or any quote whose round-0/round-3 audit reports a high-severity discrepancy. The red team must challenge meaning, not polish style.

## Remaining limitations to address in future iterations

The current validator cannot semantically resolve every ASR discrepancy or prove that a source transcript is error-free; it can only require quote-level second-source evidence and structured constraint records. Similarly, “best available quality” is validated from the recorded selector, stream metadata and hash; a platform may expose a higher source only to a logged-in account or a different client, so the downloader must preserve the actual selection evidence and stop rather than silently downgrade.

The current renderer can now record warnings, but a future version should also record font file hashes, ffmpeg version, source video hash and exact command-line arguments in `render.json`. That would make pixel-level reproduction and forensic debugging stronger.

The current red-team trigger uses a conservative keyword scan. The current source gate also uses a conservative role allow-list: only `interviewer` or `speaker` may be a hero subject; if the source is a solo speech, label the person `speaker` rather than inventing an interviewer. It should later be replaced or supplemented by a structured risk classifier that records the triggering quote IDs and rationale, while keeping the keyword fallback as a deterministic safety net.

## Final status recommendation

Use `draft` for incomplete work, `reviewed` only after four complete calibration rounds plus release integration, and `final` only after heterogeneous ASR evidence plus structured constraint adjudication also pass. Never upgrade a status by rewriting prose; status must be the consequence of the machine gate.

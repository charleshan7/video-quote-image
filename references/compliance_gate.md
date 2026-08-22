# Compliance Gate

Use this gate before any user-facing delivery. Do not call a rendered image set “final” merely because rendering succeeded.

## Status model

| Status | Meaning | Delivery rule |
|---|---|---|
| `draft` | Work in progress; one or more evidence layers are incomplete. | May be shown only when explicitly labeled draft/preview. Never package as final. |
| `reviewed` | Material, structure, frame, layout, packaging **and all four calibration rounds** pass; ASR limitations or unresolved evidence gaps may still be disclosed. | Allowed only with a preflight report that lists those limitations. Missing or incomplete calibration rounds block this status. |
| `final` | All hard gates and all four calibration rounds pass, including a heterogeneous ASR second source and structured constraint adjudication. | Only this status may be described as skill-compliant final delivery. |

## Evidence contract

The following files are mandatory for `reviewed` and `final`. The four calibration artifacts are not optional; a narrative paragraph in `translation_audit.json` cannot substitute for them:

| File | Must prove |
|---|---|
| `source_download.json` | Highest-quality direct download selector, merged media path, actual stream metadata, SHA-256 and source version evidence. |
| `audit/source_subs.srt` | Primary subtitle/transcript source used for `match` and `time`. |
| `audit/spec.json` | `hero_time`, `hero_subject`, `hero_subject_role` (`interviewer`/`speaker`), hero identity sources, and every quote’s `time` and independently selected `frame_time`. |
| `audit/quotes.json` | Candidate/source quote record before location and rendering. |
| `audit/selection_audit.json` | `structure`, `planned_count`, `actual_count`, `core_quote_index`, `rejected_quotes`, and `count_reason` for every image. |
| `audit/translation_audit.json` | Four rounds plus `primary_source_engine`, `second_source_engine` and `independent_architecture`, structured-adjudication state, changes and limitations. Every round must have `status=completed`, `artifact`, and `quote_count`. |
| `audit/review_asr_xcheck.md` or equivalent | Quote-level second-source comparison and discrepancy classification for round 0. |
| `audit/round1_self_check.json` | Exactly one row per quote with `source_en`, `current_cn`, `checks`, and `adjudication`. |
| `audit/round2_mechanical_diff.json` | Exactly one row per quote with `source_en`, `current_cn`, `diff`, and `changed`. |
| `audit/round3_adjudication.json` | Exactly one row per quote with `source_en`, `current_cn`, `claims`, `evidence_basis`, `adjudication`, and `changed`. |
| `audit/frame_audit.json` | At least five candidate frames per quote plus at least eight wide-window hero candidates per image, selected frames, roles, offsets and camera-transition notes. |
| `audit/render.json` | Actual renderer dimensions, hero height/fraction, margin, footer and hero-text state; renderer warnings must be empty. |
| `audit/release_manifest.json` | Version, requested status, image/quote counts, artifact SHA-256 hashes and release ZIP identity for the fifth-layer integration gate. |
| `audit/red_team.json` | Required only when `spec.meta.risk_flags` is non-empty; one `retain/revise/stop` challenge row per quote. |
| `audit/people.json` | Verified people records; every hero must resolve to an `interviewer` or `speaker` with source URL, source quote, verified date and confidence. An interviewee record may be included as supporting context. |
| `xiaohongshu_package.md` | Person introduction, title candidates with evidence and rejection reasons, cover, body, carousel `image_id`/`quote_ids`, comment prompt and tags. |
| `preflight_report.json` and `preflight_report.md` | Machine-readable and human-readable gate result. |

The primary subtitle source and second ASR source are different roles. Never pass a second-ASR transcript as `--subs` just to make exact-match checks pass. The source transcript is the authority for locating the displayed quote; ASR reports are evidence about recognition reliability.

## Required sequence

1. Run the material gate with `scripts/download_source.py`; require the highest-quality direct source, merged audio/video, `source_download.json`, source hash and source version before selecting quotes.
2. Build `quotes.json`, then locate `time` from the primary subtitle source. Do not hand-enter quote timestamps.
3. Run the quote-count and structure audit. Stop on count mismatch, missing core quote, fixed-count template without a per-group reason, repeated quote or unsupported half-sentence.
4. Run ASR cross-check and translation rounds. Record all high-risk differences. If the difference cannot be resolved by the available subtitle/ASR evidence and structured constraints, downgrade to `reviewed` or stop publication.
5. Extract five or more frames around each quote, choose `frame_time` separately from `time`, and audit hero candidates in a wider window.
6. Render into a new version directory. Preserve `render.json`; stop on any overflow warning rather than treating it as noise.
7. Add branding into a separate `branded/` directory. Never re-brand an already branded image.
8. Build `release_manifest.json` and compare hashes across `source_subs → quotes → spec → frames → render → branded images → package`.
9. If `spec.meta.risk_flags` is non-empty, run the quote-level red-team audit and resolve every `retain/revise/stop` decision before delivery.
10. Inspect every final image at original size, create the branded contact sheet, run preflight with `--status reviewed` or `--status final`, and only then package the ZIP.

## Hard-stop semantics

`preflight.py` exits non-zero for a missing `--zip` on a non-draft delivery, missing evidence, missing or non-best-quality download manifest, missing streams, bad duration, invalid quote structure, invalid hero role, missing hero identity evidence, fewer than eight hero candidates, time/frame-time collapse, unmatched primary subtitle text, invalid dimensions, renderer warnings, missing render metadata, incomplete people records, incomplete publication packaging, missing frame audit, missing release manifest, artifact hash mismatch, missing triggered red-team audit, corrupt ZIP, **any missing or incomplete one of rounds 0–3**, or any missing quote-level row in the four round artifacts. A `final` request additionally fails when `translation_audit.json` omits `primary_source_engine`, `second_source_engine` or `independent_architecture: true`, when the two recorded engines resolve to the same architecture family (whisper / elevenlabs-scribe / google-asr / deepgram / assemblyai — `openai-whisper` against `whisper.cpp` is the same family and is rejected regardless of what the audit declares), or when the structured adjudication artifact is incomplete. Silence is not evidence: an absent declaration fails the gate rather than passing it. A `reviewed` request may pass only when all four rounds, the release integration manifest and any triggered red-team audit are complete; ASR limitations may remain explicit warnings in the report and user-facing delivery message.

## Command

```bash
"<SKILL_DIR>/.venv/bin/python" "<SKILL_DIR>/scripts/preflight.py" \
  --root DELIVERY_DIR \
  --video VIDEO \
  --status reviewed \
  --zip DELIVERY.zip
```

`--zip` has no default, so a leftover archive from a previous delivery can never satisfy the gate. For a publication-grade delivery, use `--status final`. Treat a non-zero exit code as a stop signal; do not override it by editing the report text.

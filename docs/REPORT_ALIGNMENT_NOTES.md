# SafeChat-Guard V3 Report Alignment Notes

## Final freeze

- Final competition submission freeze: `1286f3d` (`1286f3db3e5e73f6ad7543cdbd47ed9227235b5c`).
- Clean frozen clone: `594 collected`; `594 passed, 1297 warnings in 79.27s`.
- Production equivalence: `170/170`. It proves direct-entry and production-entry consistency on the public non-holdout matrix, not real-world generalization accuracy.
- The published 330-row result is aggregate-only evidence from a self-built, one-time internal holdout. It is not an official test set and was not rerun during this documentation alignment.
- `93105e5 / 576 passed` is the earlier/pre-final delivery baseline, not the final submission freeze.

## Capability boundaries

### Variant-character normalization

V3 reserves a `variant_char` extension interface, but the frozen mapping file is empty. The final V3 does not treat variant-character or visual-similarity restoration as a formally enabled capability. Its formally enabled adversarial normalization mainly covers Unicode/control characters, symbol insertion, Emoji, homophones, pinyin, abbreviations, repeat/noise handling, and controlled separator recovery.

### Input Sanitizer

The input Sanitizer is a match-driven local rewriter. After ActionRouterV3 selects `sanitize`, it rewrites located matches in normalized text; contact cues such as “加微信” and “联系微信” use the contact-hiding placeholder, while other supplied matches use the generic replacement. The rewritten text is scanned and routed again. Only a passing recheck may be forwarded; unchanged output, rewrite failure, residual risk, or a recheck error is upgraded to `block`.

The input Sanitizer is not a complete structured-field system that independently maps phones, landlines, email addresses, WeChat IDs, identity cards, bank cards, and addresses to `[REDACTED]`, `[PRIVACY]`, or `[AD]`.

### OutputGuard

OutputGuard is an independent output-safety decision layer with `block_threshold=80` and `sanitize_threshold=40`. It consumes base scan detections as one evidence source, then adds privacy regex and extra high-risk rules before sanitizing or returning a safe refusal. Its structured privacy handling covers phone, email, id_card, bank_card, URL, IP, WeChat, QQ, and address patterns.

The core trained/input risk label space remains `normal`, `ad`, `porn`, `violence`, and `sensitive`. Output-side categories such as `privacy`, `illegal`, and `self_harm` are runtime extensions; `abuse` has output-side label and safe-response support. Model output is not sent through the complete ActionRouterV3 flow again.

### Evaluation terminology

- 330 = self-built, one-time internal holdout; only public aggregate evidence is used.
- 170/170 = production equivalence, not a generalization metric.
- 200 Gold = provisional single-review gold while the second reviewer's 40-row blind sample remains incomplete.

### Performance evidence

The work report records Mean 35.21 ms, P50 28.88 ms, P95 79.92 ms, and Throughput 28.36 req/s.

These figures are recorded as a pre-freeze local performance experiment. The frozen Git commit does not currently contain a complete benchmark artifact directly binding the exact figures to the final commit. Any later reproduction must use the public dev data, be labeled as a separate run, and must not access the internal holdout. No untracked local performance JSON is included automatically by this documentation alignment.

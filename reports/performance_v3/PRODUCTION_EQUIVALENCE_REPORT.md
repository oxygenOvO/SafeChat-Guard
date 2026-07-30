# SafeChat-Guard V3 production equivalence report

Date: 2026-07-30

## Scope

This acceptance compares the frozen V3 direct detection entry, `SafeChatPipeline.detect_text`, with the production conversation entry, `SafeChatPipeline.handle_chat`. Both entries load the same frozen V3 models and threshold configuration. The production entry uses a fixed safe reply override and disables audit persistence so the comparison isolates the deployed filtering path.

No internal holdout file, text, prediction, metric function or evaluation command is read or executed. No model, threshold, rule, dataset or action-core change is made.

## Public non-holdout inventory

| Suite | Cases |
|---|---:|
| Existing manual adversarial matrix | 40 |
| Existing context boundary matrix | 32 |
| Existing deterministic generalization matrix | 62 |
| Existing deterministic safety-negative matrix | 36 |
| **Total** | **170** |

## Equivalence results

| Suite | Production completed | Action identical | Label identical | No fallback |
|---|---:|---:|---:|---:|
| manual adversarial | 40/40 | 40/40 | 40/40 | 40/40 |
| context boundary | 32/32 | 32/32 | 32/32 | 32/32 |
| generalization | 62/62 | 62/62 | 62/62 | 62/62 |
| safety negative | 36/36 | 36/36 | 36/36 | 36/36 |
| **Total** | **170/170** | **170/170** | **170/170** | **170/170** |

Failed case IDs: none.

## Runtime identity

```text
active_filter_version=v3
v3_enabled=true
v3_ready=true
risk_model_loaded=true
block_model_loaded=true
fallback_active=false
fallback_reason=null
risk_model_sha256=136b9952869c6662eaa77e65d3a22e3cac3eddfe3f751ffa55bc99fd80845785
block_model_sha256=412f46781bcba63de8ada1d8781296acdbb25447f303130d0926cff6bd176b21
threshold_config_sha256=5332006befae66475c9e7449d7c48dafd2ed6e5dba3ca6a5f7c0d2179783c3a2
```

## Conclusion

The frozen V3 direct entry and production SafeChatPipeline entry agree on action and label for all 170 public non-holdout cases. Every production call used V3 and the fallback count was zero.

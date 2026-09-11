# Phase 2 thesis results

These results close the previously missing evidence. The normalization values below come from the locked 741-record test, after model selection on the separate 926-record validation population. No training or retuning was performed after opening the test.

## Locked normalization test

| System | WER | CER | Exact match | Change F1 | Protected-token accuracy | Exact-match 95% bootstrap CI |
|---|---:|---:|---:|---:|---:|---:|
| Raw control | 0.299413 | 0.223776 | 0.059379 | 0.000000 | 1.000000 | 0.0432 to 0.0756 |
| Most-frequent replacement | 0.358190 | 0.151573 | 0.022942 | 0.190476 | 1.000000 | 0.0135 to 0.0351 |
| Rules | 0.106273 | 0.062317 | 0.299595 | 0.485620 | 1.000000 | 0.2672 to 0.3360 |
| ByT5 | 0.014666 | 0.009080 | 0.936572 | 0.954180 | 0.966262 | 0.9190 to 0.9541 |
| Selective ByT5 (selected) | 0.021886 | 0.014266 | 0.932524 | 0.946045 | 1.000000 | 0.9150 to 0.9514 |
| Rules then ByT5 | 0.017825 | 0.011144 | 0.913630 | 0.942547 | 0.970310 | 0.8934 to 0.9339 |

Interpret these figures as agreement with the expert normalization reference. They do not independently prove semantic correctness. The 926-record validation results may still be reported as model-selection evidence, but they must not be labelled as held-out test performance.

## Supplementary robustness analysis

# Supplementary fixed-protocol retrieval robustness

This is a post-hoc robustness analysis using the already-frozen configuration. It performs no training, model selection, or retuning. The clean condition reproduces the frozen RQ4 result exactly. All scores measure agreement with the recorded historical action family, not technical correctness.

- Representation: Selective ByT5
- Retrieval: canonical BM25
- Prior temperature: tau = 0.15
- Aggregation: cluster-expanded
- Evaluable locked-test queries: 828
- Perturbation seed: 42

| Condition | Level | Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@5 | Macro recall | Hit@1 drop | Top family changed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| clean | 0.00 | 0.7899 | 0.9686 | 0.9952 | 0.8766 | 0.9067 | 0.2802 | 0.0000 | 0.0000 |
| truncation | 0.10 | 0.7766 | 0.9650 | 0.9879 | 0.8652 | 0.8958 | 0.2491 | 0.0133 | 0.0399 |
| truncation | 0.20 | 0.7754 | 0.9626 | 0.9879 | 0.8625 | 0.8937 | 0.2504 | 0.0145 | 0.0640 |
| truncation | 0.30 | 0.7814 | 0.9614 | 0.9867 | 0.8643 | 0.8948 | 0.2563 | 0.0085 | 0.0797 |
| spelling_noise | 0.05 | 0.7729 | 0.9662 | 0.9928 | 0.8638 | 0.8965 | 0.2658 | 0.0169 | 0.0592 |
| spelling_noise | 0.10 | 0.7560 | 0.9577 | 0.9915 | 0.8555 | 0.8896 | 0.2442 | 0.0338 | 0.0809 |
| missing_structure | 1.00 | 0.7899 | 0.9686 | 0.9952 | 0.8766 | 0.9067 | 0.2802 | 0.0000 | 0.0000 |

## Interpretation boundary

Truncation and spelling noise modify only the canonical problem-text retrieval channel; the structured fields remain those extracted from the clean query. The missing-structure condition is a negative control for the selected canonical-BM25 mode and is therefore expected not to change its ranking. Joined multi-problem queries are not assigned a misleading single action-family gold label and are outside this quantitative analysis.

## Frozen input identity

- Final RQ4 result SHA-256: `37ef347cc07c92c45944ee9f5a88a4dccade3937716f51f1cd7c8838397ec560`
- Final RQ4/RQ5 freeze manifest SHA-256: `b1b8469fe2f6685644867a0761a885635132d8a3d4604c322735a419d70fbf98`
- Selective implementation SHA-256: `0e32f5e457d98b36875f5b7a6b9bb190c6b71f57159dc4e07cb10990502589e8`

## Mandatory thesis edits

1. Change the RQ1 evaluation population to the locked 741-record test and keep the 926 records labelled validation only.
2. Replace the normalization result table and its confidence interval with the values above.
3. Replace the Section 5.8 placeholder with the robustness table above and label it supplementary post-hoc fixed-protocol analysis.
4. Do not alter or rerun the frozen RQ4/RQ5 results.

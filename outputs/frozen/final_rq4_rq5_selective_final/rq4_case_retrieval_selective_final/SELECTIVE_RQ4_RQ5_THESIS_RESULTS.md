# Selective-ByT5 RQ4/RQ5 thesis results

Generated: 2026-09-08T21:23:47.546687+00:00

## Frozen experimental identity

- Representation: Selective ByT5
- Records: 6,169
- Split: {'train': 4319, 'test': 925, 'dev': 925}
- Evidence clusters: 3,363
- Leakage groups: 1,820
- Near-duplicate threshold: `0.87` (largest transitive group: 1176 records)
- Oversized groups forced wholly to TRAIN: [{'group_id': 'SLG-b3206d7ecdbe6a45', 'records': 1176, 'share': 0.1906305722159183, 'split': 'train'}, {'group_id': 'SLG-da80ea9f2680fe6a', 'records': 908, 'share': 0.14718755065650835, 'split': 'train'}]
- Split leakage groups: {'train': 1289, 'dev': 280, 'test': 251}
- Leakage-group crossings: 0
- Evidence-cluster crossings: 0
- Evidence clusters spanning leakage groups: 0
- Selected retrieval mode: `selective_canonical_bm25`
- Selected prior temperature: `0.15`
- Aggregation: `cluster_expanded`
- Retrieval mode selection: tau=0 cluster-expanded: max macro recall, then MRR, then Hit@1
- Prior-temperature selection: Hit@1 and Hit@3 within 0.01 of tau=0; then max macro recall, MRR, Hit@1, smaller tau
- The retrieval query uses normalized PROBLEM text and problem-only Selective SpERT structure. ACTION is opened only after retrieval.
- The earlier lexicon-only temperature sweep is treated as post-hoc scoping evidence; it is not a confirmatory result.
- Selective V2/V3 are retained only as unopened pilots. The final protocol fixes 0.87, assigns all >5% transitive groups wholly to TRAIN, and reports only FINAL locked-test results.

## RQ4 locked-test automatic results

| Configuration | Hit@1 | Hit@3 | MRR | Macro recall |
|---|---:|---:|---:|---:|
| DEV-selected complete system | 0.7899 | 0.9686 | 0.8766 | 0.2802 |
| Majority-family baseline (Replace) | 0.7609 | 0.7609 | 0.7609 | 0.1429 |
| Same mode, tau=0 | 0.7959 | 0.9698 | 0.8798 | 0.2523 |
| Representative-only action ablation | 0.7983 | 0.9698 | 0.8793 | 0.2911 |

Pattern-set recall@3: **0.7911**  
Pattern-set recall@5: **0.7923**  
Recorded multi-family set recall@3: **0.9394**  
Answer rate: **1.0000**
Hit@1 above majority-family baseline: **0.0290**  
Macro recall above majority-family baseline: **0.1373**  
Selected Hit@1 95% bootstrap CI: **[0.7620471014492755, 0.8188405797101449]**  
Selected macro-recall 95% stratified-bootstrap CI: **[0.24843384488182627, 0.31222212139137595]**  
Selected-vs-tau0 Hit@1 difference: **-0.0060**; McNemar exact p = **0.4049**.

The primary metrics measure agreement with recorded historical action families. They do not measure technical correctness, safety, regulatory applicability, or airworthiness.

## Per-family locked-test Hit@1

| Family | Queries | Hit@1 |
|---|---:|---:|
| Adjust | 66 | 0.4242 |
| Calibrate | 1 | 0.0000 |
| Diagnose | 45 | 0.4444 |
| Inspect | 40 | 0.0500 |
| Repair | 23 | 0.0000 |
| Replace | 630 | 0.9556 |
| Service | 23 | 0.0870 |

## RQ5 historical-agreement calibration

- ECE (10 bins): 0.0505
- Brier score: 0.1195
- Calibration was fitted on DEV and evaluated on locked TEST.
- Lower-probability, single-support and nearest-only evidence remains visible; probability is a grade, not a display gate.

## Blinded manual review

- Queries: 100
- Pairs: 500
- Problem relevance Hit@1: 0.9200
- Problem relevance Hit@5: 0.9700
- Usable action evidence Hit@1: 0.9200
- Usable action evidence Hit@5: 0.9700
- With one reviewer, inter-rater agreement cannot be estimated.

## Original raw frozen run — contextual reference only

| Run | Hit@1 | Hit@3 | MRR | Macro recall |
|---|---:|---:|---:|---:|
| Original raw/TRUE-RAW-SpERT freeze | 0.7983 | 0.9503 | 0.8726 | 0.3555 |
| New Selective complete system | 0.7899 | 0.9686 | 0.8766 | 0.2802 |

**Comparison limitation:** the Selective protocol rebuilds canonical clusters and leakage groups, so its TEST partition is not identical to the original raw TEST partition. The table is descriptive, not a paired causal estimate of normalization benefit.

## Evidence-presentation safeguards

- Cluster-expanded actions are grouped into `(family, component, fault)` patterns.
- Every cluster contributes at most one vote per family and pattern.
- Single-cluster actions are displayed as Limited historical evidence.
- Positive, unknown, negative and mixed outcomes remain distinguishable.
- Historical work-order IDs and raw/normalized text provide provenance.
- The system presents evidence and alternatives; it does not generate or approve a maintenance procedure.

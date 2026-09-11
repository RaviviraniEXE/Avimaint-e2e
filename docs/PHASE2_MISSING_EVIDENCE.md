# Phase 2 — Complete the missing experimental evidence

## Purpose

Phase 1 established that the repository is substantially frozen, but two thesis evidence items are not complete at the audited commit:

Audited GitHub commit: `2fd8a458f1a2b2dadfacae48d89daafd4403af1f`.

1. The 741-record intrinsic normalization TEST metrics are not committed.
2. Existing robustness results use the older `rules_then_byt5` hybrid protocol, not the final Selective representation and final RQ4 retrieval configuration.

Phase 2 completes only these two items. It does not train or retune any model, alter the validation selection, or modify an existing freeze.

## One launcher

From an Anaconda Prompt in `D:\avimaint-e2e-research`:

```bat
PHASE2_RUN_AND_FREEZE.bat
```

This default `SAFE` mode:

- validates the frozen validation selection;
- reuses the 741-record normalization TEST outputs when they already exist locally;
- refuses to open the missing normalization TEST;
- freezes validated normalization evidence;
- runs the fixed Selective robustness analysis;
- requires exact clean-result parity with the already-frozen RQ4 result;
- writes manifests and SHA-256 checksums.

If and only if SAFE reports that the normalization TEST outputs are absent, review the frozen validation selection and explicitly run:

```bat
PHASE2_RUN_AND_FREEZE.bat CONFIRM_TEST
```

`CONFIRM_TEST` calls the repository's existing gated `scripts\normalization\06_run_final_test_once.bat`; it does not contain a training command.

## Outputs

Successful execution creates:

- `outputs\frozen\phase2_normalization_intrinsic_test_v1`
- `outputs\frozen\phase2_selective_robustness_v1`
- `outputs\frozen\phase2_evidence_completion_v1`

Each component freeze contains a `FREEZE_MANIFEST.json` and `SHA256SUMS.txt`. The completion folder contains the final evidence manifest and a thesis-reporting guide.

## Fixed robustness protocol

| Item | Frozen value |
|---|---|
| Representation | Selective ByT5 |
| Partition | Final frozen TEST |
| Records / evaluable queries | 925 / 828 |
| Retrieval mode | Selective canonical BM25 |
| Tau | 0.15 |
| Aggregation | Cluster-expanded |
| Stressors | Truncation 10/20/30%; spelling noise 5/10%; missing structure |
| Metrics | Hit@1/3/5, MRR, nDCG@5, macro action-family recall |
| Tuning | None |
| Claim type | Supplementary post-hoc, fixed protocol |

Truncation and spelling noise modify only the normalized problem-text channel. The missing-structure condition removes structured fields while retaining clean text. This channel isolation should be stated in the thesis.

## Thesis reporting rules

- Report the exact evaluated population next to every result.
- Keep the 741-record intrinsic normalization TEST separate from the 225-record normalization-to-SpERT ablation TEST.
- Describe retrieval scores as agreement with the recorded historical action family, not as technical correctness or maintenance approval.
- Call the final Selective robustness study supplementary/post-hoc. The main RQ4 TEST had already been opened and frozen before this Phase 2 protocol was executed.
- Do not replace or silently combine the older `rules_then_byt5` robustness results with this final Selective run.

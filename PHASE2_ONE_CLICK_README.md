# AviMaint thesis Phase 2 one-click hotfix

This overlay completes the two experimental items that are still missing from the thesis:

1. the locked 741-record normalization test selected from the separate 926-record validation population; and
2. a supplementary post-hoc robustness analysis using the already-frozen Selective ByT5 retrieval protocol.

It does **not** train, tune, or select a model. It does **not** modify or reopen the frozen RQ4/RQ5 experiment.

## Install

Extract the ZIP directly into:

```text
D:\avimaint-e2e-research
```

Allow Windows to merge the `scripts` directory. The package adds new Phase 2 files; it does not replace the existing model or research outputs.

## Run from Anaconda Prompt

Start with SAFE mode:

```bat
cd /d D:\avimaint-e2e-research
PHASE2_RUN_AND_FREEZE.bat
```

SAFE mode verifies the frozen validation selection and reuses existing locked-test evidence. If the 741-record test outputs are absent, it stops before opening the test and prints the missing files.

Only after reviewing that message, run:

```bat
PHASE2_RUN_AND_FREEZE.bat CONFIRM_TEST
```

This performs the previously unopened normalization test once, runs the fixed-protocol robustness analysis, checks exact parity with the frozen clean RQ4 result, and creates an immutable Phase 2 freeze.

To verify an already completed freeze without recomputing anything:

```bat
PHASE2_RUN_AND_FREEZE.bat VERIFY_ONLY
```

## Final outputs

```text
outputs\frozen\phase2_missing_evidence_final\
  FREEZE_MANIFEST.json
  SHA256SUMS.txt
  PHASE2_THESIS_RESULTS.md
  normalization_test\
  robustness\
  context\
```

Use `PHASE2_THESIS_RESULTS.md` to update the thesis. It contains the locked normalization table, bootstrap intervals, robustness table, interpretation boundaries, and the exact edits required.

## Required local prerequisites

- Conda environment `avimaint-normalization`
- Conda environment `avimaint-dash`
- The locally trained ByT5 checkpoint referenced by `outputs\normalization\models\byt5_gold_v1\run_manifest.json`
- Existing frozen Selective RQ4/RQ5 artifacts
- Existing Selective problem-only prediction artifacts

Large model weights are intentionally not included in this overlay.

## Safety behaviour

- A partial or mismatched test result fails closed.
- Existing valid prediction and metric files are reused.
- A fully verified robustness staging directory is recovered after an interrupted final move, without recomputing the study.
- The robustness clean condition must reproduce the frozen RQ4 metrics within an absolute tolerance of `1e-12`.
- An existing Phase 2 freeze is verified and reused; it is never overwritten.
- Every frozen file is protected by SHA-256 checksums.
- All retrieval scores are labelled as historical action-family agreement, not technical correctness or maintenance approval.
- Seven automated self-tests run before any research step.

# AviMaint Phase 2 freeze hotfix v1.2

This is a minimal local overlay for the Phase 2 v1.1 package. It fixes the
`NameError: name 'os' is not defined` failure in
`scripts\thesis_phase2\phase2_freeze.py` and adds a regression test for the
final atomic staging-to-freeze promotion.

## Scope and safety

- Replaces only `phase2_freeze.py` and `test_phase2_hotfix.py`.
- Does not contain or modify prediction outputs, metrics, model checkpoints,
  the frozen RQ4/RQ5 result, or the recovered robustness result.
- Does not train or retune any model.
- Does not perform any GitHub operation.
- Keeps the fail-closed behavior: an existing Phase 2 freeze is verified and
  reused, never overwritten.

## Install

1. Extract this ZIP directly into `D:\avimaint-e2e-research`.
2. Allow Windows to replace the following two files only:

   - `scripts\thesis_phase2\phase2_freeze.py`
   - `scripts\thesis_phase2\test_phase2_hotfix.py`

## Resume Phase 2

Run the existing launcher from Anaconda Prompt:

```bat
cd /d D:\avimaint-e2e-research
PHASE2_RUN_AND_FREEZE.bat CONFIRM_TEST
```

The launcher will verify and reuse the already completed 741-record
normalization test and the recovered robustness result. It will then create
the missing immutable Phase 2 freeze and run final verification. Do not use
`VERIFY_ONLY` until the final freeze has been created successfully.

## Expected evidence in the log

- `Ran 8 tests ... OK`
- `PHASE2_NORMALIZATION_TEST_VERIFIED`
- `REUSE verified robustness result: ...phase2_final_protocol_robustness`
- `PHASE2_FREEZE_COMPLETE`
- `PHASE2_FREEZE_VERIFIED`
- `PHASE 2 COMPLETE AND VERIFIED`

## Technical change

The failing code already used `os.replace(stage, destination)` for an atomic
directory promotion, but the module omitted `import os`. Version 1.2 adds the
missing import. The new test constructs a synthetic Phase 2 evidence tree and
executes the full final promotion path, so this specific error is caught by
the self-tests before the research workflow starts.

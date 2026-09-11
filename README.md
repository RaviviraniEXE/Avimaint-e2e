# AviMaint thesis Phase 2 package

This repository overlay completes the two evidence gaps found in Phase 1 without training or retuning:

1. validate/freeze the 741-record intrinsic normalization TEST;
2. evaluate/freeze robustness for the final Selective retrieval protocol.

Copy the contents of this package into the root of `D:\avimaint-e2e-research`, preserving folders. Then open Anaconda Prompt in that repository and run:

```bat
PHASE2_RUN_AND_FREEZE.bat
```

The default is `SAFE`. If it reports that the normalization TEST is still sealed and its outputs are absent, follow the review instructions and explicitly use:

```bat
PHASE2_RUN_AND_FREEZE.bat CONFIRM_TEST
```

See `docs\PHASE2_MISSING_EVIDENCE.md` for the protocol, outputs, and thesis claim boundaries.

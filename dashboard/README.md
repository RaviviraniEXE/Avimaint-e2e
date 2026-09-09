---
title: AviMaint DSS
emoji: ✈️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# AviMaint-DSS

Deployment-ready dashboard for the frozen Selective-ByT5 RQ4/RQ5 system with a separate operational evidence-matching layer.

The default `frozen_artifacts` profile needs no neural weights. It serves the final normalized corpus, precomputed Selective SpERT structure, canonical BM25 retrieval, the DEV-selected `tau = 0.15` family vote, and frozen RQ5 calibration parameters.

The Diagnose page does not alter the frozen thesis metrics. For practical display, every action option must match the query's target component and fault. Position is a ranking preference and a visible evidence stratum: support at the reported position, at other positions, and with no recorded position is never pooled silently. Repeated action patterns rank by distinct evidence-cluster support and same-position support breaks ties; a pattern observed once remains visible as limited evidence. Different action targets remain separate cards. Corrective and assessment actions are independent options because the source does not annotate procedural order.

When the query exactly matches a frozen TRAIN problem, the dashboard also compares the complete score-free Selective SpERT entity-relation signature. For unseen wording, a deterministic schema adapter displays transparent `ISSUE_ON_ITEM` and `HAS_LOCATION` links but does not claim SpERT inference or full-graph equality.

Outcome labels are preserved. A replacement or repair with an unknown outcome is shown as **corrective action documented; post-action outcome not recorded**—never as a success and never as a failure. Direct work-order lookup, optional disclosed anchor correction, clickable component–fault drill-down, watchlist import/export, deep-linked diagnosis queries, keyboard shortcuts and print styling are included.

Build locally:

```bash
docker build -t avimaint-dss .
docker run --rm -p 7860:7860 -v avimaint-feedback:/data avimaint-dss
```

On Windows, start Docker Desktop and run `START_DASHBOARD.bat`. It verifies the frozen files, builds the image, and serves the dashboard at `http://127.0.0.1:7860`.

The local launcher keeps the optional usefulness feedback in a Docker volume. Only a SHA-256 query fingerprint and a small evidence snapshot are stored; the problem text is not stored, and the rating is explicitly not a technical-correctness label. On Hugging Face Spaces, files written to the container are lost when the Space restarts. The dashboard itself is unaffected, but feedback remains ephemeral unless a Hugging Face Storage Bucket or another external store is connected in a later deployment profile.

Verify before deployment:

```bash
python scripts/verify_release.py
```

After `npm run build` in `frontend/`, add `--require-frontend` to verify that every page has exactly one production bundle and no stale page chunks remain.

No model folders need to be copied for this release. The two exact optional checkpoints are documented in `models/manifest.json` only for a future live-inference profile; this dashboard does not load them.

Deploy on Hugging Face Spaces:

1. Create a new Space and choose the **Docker** SDK.
2. Copy the contents of this folder to the root of the Space repository.
3. Commit and push. The container serves the frontend and API together on port `7860`.
4. Optional: connect a Hugging Face Storage Bucket or another external store before using feedback as durable research data.

For continuous deployment from the complete research repository, keep this directory at `dashboard/` and install `.github/workflows/deploy-dashboard.yml` at the repository root. Configure the GitHub Actions secret `HF_TOKEN` and repository variable `HF_SPACE_REPO_ID=owner/space-name`. A push to `main` that changes this directory then runs the backend tests, frontend tests and build, frozen-artifact verification, Docker build and live-container health check. The clean `dashboard/` source is synchronized to the Space root only after every validation gate succeeds.

Required runtime artifacts are already under `data/`: the 6,169-row frozen Selective corpus, the 6,169 problem-only Selective SpERT predictions, the final split and selection locks, the frozen RQ4 result, and the RQ5 calibrator parameters.

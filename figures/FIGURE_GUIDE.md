# AviMaint-DSS thesis figures — rebuilt set

Seventeen vector figures. Every label is **Calibri 10 pt** at the intended print size, and each
SVG is authored at a native width of **160 mm** so the text lands at exactly 10 pt when inserted
at that width.

## Inserting them in Word

Insert → Pictures → This Device, then set the width to **16.0 cm** and keep the aspect ratio.
Add the caption with References → Insert Caption (label: Figure) so numbering stays automatic.
Do not paste a screenshot of an SVG, and do not resize away from 16 cm — the 10 pt text scales
with the frame.

If Calibri is missing on the machine that opens the file, Carlito substitutes with the same
metrics. A 2× PNG of each figure is provided in `PNG_2x/` for anyone who cannot place SVG.

## The figures

| Figure | File | Caption to use | Evidence status |
|---|---|---|---|
| 1.1 | Figure_1_1_Thesis_structure | How the chapters build one bounded planning-support claim | Conceptual |
| 2.1 | Figure_2_1_Literature_landscape | Five literature strands and the gap this thesis addresses | Conceptual |
| 3.1 | Figure_3_1_Evidence_layers | Five evidence layers and what each one is allowed to prove | Conceptual |
| 4.1 | Figure_4_1_Normalization_protocol | Cluster-safe normalization experiment and the one-way test gate | Protocol |
| 4.2 | Figure_4_2_Normalization_test | Locked normalization test on 741 held-out records | Frozen test, 741 records |
| 4.3 | Figure_4_3_Matched_SpERT | Representation-matched SpERT on one frozen 225-record test | Frozen test, 225 records |
| 5.1 | Figure_5_1_Gold_entity_support | Entity mention support in the 1,600-record gold corpus | Gold corpus |
| 6.1 | Figure_6_1_Overall_IE | Four extraction architectures on one frozen 225-record gold test | Frozen test, 225 records |
| 6.2 | Figure_6_2_Per_class_entities | Per-class entity F1 across the four architectures | Frozen test, 225 records |
| 6.3 | Figure_6_3_Per_class_relations | Per-class relation F1 across the four architectures | Frozen test, 225 records |
| **7.1** | Figure_7_1_Case_and_subgraph | **One work order as a case and a silver subgraph** | **Silver, record 100005** |
| 8.1 | Figure_8_1_Query_contents | What the retrieval query carries, and what is withheld | Schematic |
| 8.2 | Figure_8_2_Online_offline_boundary | Offline historical structure and the two separate query paths | Schematic |
| 8.3 | Figure_8_3_Evidence_option | What a displayed historical option shows the reviewer | Schematic |
| 8.4 | Figure_8_4_Abstention_logic | How an option becomes eligible, and when the system abstains | Schematic |
| 8.5 | Figure_8_5_Calibration | Risk–coverage curve and reliability diagram | Locked test, 828 queries |
| B.1 | Figure_B_1_Gold_relation_support | Relation instance support in the 1,600-record gold corpus | Gold corpus |

Figure 7.1 is new and fills the only substantive chapter that had no figure. Figure 6.4 is
deliberately absent: a single observation at n_train = 1,275 is not a learning curve.

## What changed against the previous set

- **Figure 4.2** previously drew word error rate and exact match on one bar track with no axis,
  so a WER of 0.2994 looked longer than an exact match of 5.94%. It is now three panels, each
  with its own scale and an explicit note that bar length is comparable only within a panel.
- **Figures 6.1–6.3** previously used an axis from 0 to 1 while every value sat above 0.6, leaving
  most of the plot empty. Axes are now clipped to the data range and every bar carries its value,
  so the figure is no longer less precise than the table beside it.
- **Figures 6.2 and 6.3** used four near-overlapping dots per row in colours that failed a
  colour-vision check (teal against blue at ΔE 11.7 for normal vision, below the readable floor).
  They are now four small multiples: position carries model identity, colour only reinforces it,
  and the figures survive greyscale printing.
- **Figure 1.1** previously varied its accent colour with no meaning. Colour now marks only the
  chapters that answer a research question on a frozen test, and Chapter 10 was added.
- Series colours are drawn from a palette validated for colour-vision deficiency, and every bar
  is directly labelled, which satisfies the contrast relief rule.

## Interpretation guardrails to keep in the captions

- Figure 4.2 compares six systems on one locked 741-record test. Selective ByT5 remains the
  preselected system even though pure ByT5 records the lower word error rate.
- Figure 4.3 uses five separately trained SpERT models on the 225-record IE test, not the
  741-record normalization test. Do not interchange the denominators.
- Figures 5.1 and B.1 count mentions across all 1,600 gold records. Figures 6.2 and 6.3 report F1
  against 225-record test support. REFERENCE and ACTION_FOLLOWS_REFERENCE have n = 2 on the test,
  so their perfect scores carry no evidential weight.
- Figures 8.1 to 8.4 are schematics of the documented protocol, not captures of the deployed
  interface. If a screenshot is required, capture the current release and replace them.
- Figure 7.1 shows SpERT predictions. A relation score is the model's confidence in its own
  output, not evidence that the recorded repair was correct.

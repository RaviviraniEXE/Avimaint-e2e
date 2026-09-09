import { useEffect, useState } from "react";
import { CheckCircle2, LockKeyhole, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import type { EvaluationResponse } from "../api/types";
import { GroupedHits } from "../components/Charts";
import { ErrorState, LoadingState, MetricCard, Notice, PageHeader, Section } from "../components/ui";
import { percent, score } from "../utils";

function numberAt(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function EvaluationPage() {
  const [data, setData] = useState<EvaluationResponse | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api.evaluation().then((value) => active && setData(value)).catch((reason) => active && setError(reason.message));
    return () => { active = false; };
  }, []);
  if (error) return <><PageHeader title="Frozen research evaluation" description="Locked RQ4/RQ5 evidence." /><ErrorState message={error} /></>;
  if (!data) return <><PageHeader title="Frozen research evaluation" description="Locked RQ4/RQ5 evidence." /><LoadingState label="Reading frozen evaluation summaries…" /></>;

  const { rq4, rq5, manual, lock } = data.frozen;
  const metrics = rq4?.selected_mode_metrics || {};
  const intervals = rq4?.selected_bootstrap_intervals || {};
  const baseline = metrics.majority_family_baseline || {};
  const phaseA = manual?.phase_a || {};
  const phaseB = manual?.phase_b || {};
  const complete = Boolean(rq4 && rq5 && manual && lock?.locked);
  const problemHits = [numberAt(phaseA.problem_relevance_hit_at_1), numberAt(phaseA.problem_relevance_hit_at_3), numberAt(phaseA.problem_relevance_hit_at_5)];
  const actionHits = [numberAt(phaseB.usable_historical_action_evidence_hit_at_1), numberAt(phaseB.usable_historical_action_evidence_hit_at_3), numberAt(phaseB.usable_historical_action_evidence_hit_at_5)];
  return (
    <>
      <PageHeader eyebrow="Immutable Selective thesis evidence" title="Frozen RQ4 and RQ5 evaluation" description="The selected mode and tau were fixed on DEV, TEST was opened once, and all reported identities are checksummed. Dashboard presentation grouping does not alter these results." actions={<span className={`lock-state ${complete ? "locked" : "missing"}`}><LockKeyhole size={17} />{complete ? "Freeze locked" : "Freeze incomplete"}</span>} />
      {!complete && <Notice kind="warning">One or more frozen summaries are missing. Run `FINAL_11_VERIFY_ALL.bat` and verify the frozen output directory before citing results.</Notice>}
      <div className="metric-grid six">
        <MetricCard label="RQ4 Hit@1" value={percent(numberAt(metrics.hit_at_1), 1)} detail={`95% CI ${percent(numberAt(intervals.hit_at_1_95ci?.[0]), 1)}–${percent(numberAt(intervals.hit_at_1_95ci?.[1]), 1)} · majority ${percent(numberAt(baseline.hit_at_1), 1)}`} />
        <MetricCard label="RQ4 Hit@3" value={percent(numberAt(metrics.hit_at_3), 1)} detail={`Majority baseline ${percent(numberAt(baseline.hit_at_3), 1)}`} />
        <MetricCard label="RQ4 Hit@5" value={percent(numberAt(metrics.hit_at_5), 1)} detail="Locked TEST · no bootstrap interval reported" />
        <MetricCard label="Macro family recall" value={percent(numberAt(metrics.macro_action_family_recall), 1)} detail={`95% CI ${percent(numberAt(intervals.macro_recall_95ci?.[0]), 1)}–${percent(numberAt(intervals.macro_recall_95ci?.[1]), 1)} · majority ${percent(numberAt(baseline.macro_action_family_recall), 1)}`} />
        <MetricCard label="RQ5 ECE" value={score(numberAt(rq5?.ece_10_bins))} detail="10 bins" />
        <MetricCard label="RQ5 Brier" value={score(numberAt(rq5?.brier_score))} detail="Historical agreement" />
      </div>
      <Notice><b>Calibration boundary:</b> RQ5 estimates agreement with recorded historical action families. It is not a probability of safety, technical correctness, applicability, approval, or aircraft release.</Notice>
      <div className="two-column">
        <Section title="Blinded semantic review" description="Problem relevance and historical action usefulness at retrieval depths 1, 3 and 5.">
          <GroupedHits problem={problemHits} action={actionHits} />
        </Section>
        <Section title="Manual-review evidence" description="100 locked-TEST queries, 500 blinded problem pairs, and 433 problem-relevant action pairs.">
          <div className="review-summary">
            <div><CheckCircle2 size={20} /><span><b>{percent(numberAt(phaseA.problem_relevance_hit_at_5), 1)}</b> of queries found relevant or partially relevant problem evidence by rank 5.</span></div>
            <div><CheckCircle2 size={20} /><span><b>{percent(numberAt(phaseB.usable_historical_action_evidence_hit_at_5), 1)}</b> found usable historical action evidence by rank 5.</span></div>
            <div><ShieldCheck size={20} /><span><b>{percent(numberAt(phaseB.applicable_or_partial_rate_among_problem_relevant_pairs), 1)}</b> of problem-relevant pairs contained at least partially useful action evidence.</span></div>
            <div><ShieldCheck size={20} /><span><b>{percent(numberAt(phaseB.clearly_applicable_rate_among_problem_relevant_pairs), 1)}</b> were clearly useful historical actions.</span></div>
          </div>
          <p className="limitation">Limitation: single-reviewer/AI-assisted judgments do not provide inter-rater reliability.</p>
        </Section>
      </div>
      <Section title="Frozen protocol boundary" description="The retrieval mode was selected on DEV before TEST was opened once.">
        <div className="protocol-grid"><div><span>Selected mode</span><b>{rq4?.selected_mode || "Unavailable"}</b></div><div><span>TEST queries</span><b>{numberAt(metrics.queries).toLocaleString()}</b></div><div><span>Candidate split</span><b>TRAIN only</b></div><div><span>Manual review</span><b>Two blinded phases</b></div></div>
        <p className="page-note">{data.warning}</p>
      </Section>
    </>
  );
}

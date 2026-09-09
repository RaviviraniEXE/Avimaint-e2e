import { useEffect, useState } from "react";
import { AlertTriangle, ClipboardCheck, Database, GitCompareArrows, Sparkles } from "lucide-react";
import { api } from "../api/client";
import type { OverviewResponse } from "../api/types";
import { HorizontalBars, OutcomeDonut } from "../components/Charts";
import { ErrorState, LoadingState, MetricCard, Notice, PageHeader, Section } from "../components/ui";
import { integer } from "../utils";

export function OverviewPage({ onDiagnose }: { onDiagnose: () => void }) {
  const [data, setData] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    api.overview().then((value) => active && setData(value)).catch((reason) => active && setError(reason.message));
    return () => { active = false; };
  }, [reload]);

  return (
    <>
      <PageHeader
        eyebrow="Fleet history briefing"
        title="Maintenance planning overview"
        description="Decision-relevant patterns from all 6,169 normalized historical work orders. Diagnosis remains restricted to the frozen TRAIN evidence library."
        actions={<button className="button primary" type="button" onClick={onDiagnose}><Sparkles size={17} /> Diagnose a problem</button>}
      />
      {error && <ErrorState message={error} retry={() => setReload((value) => value + 1)} />}
      {!data && !error && <LoadingState label="Loading corpus overview…" />}
      {data && (
        <>
          <div className="metric-grid">
            <MetricCard label="Most recurring defect" value={data.kpis.most_recurring_defect || "—"} detail={`${integer.format(data.kpis.most_recurring_defect_orders || 0)} historical work orders`} icon={<Database size={19} />} />
            <MetricCard label="Repeat problems with action disagreement" value={`${(data.kpis.multi_action_cluster_pct || 0).toFixed(1)}%`} detail={`${integer.format(data.kpis.multi_action_clusters || 0)} of ${integer.format(data.kpis.repeated_clusters || 0)} repeated evidence clusters`} icon={<GitCompareArrows size={19} />} />
            <MetricCard label="Defects with one recorded case" value={integer.format(data.kpis.single_record_defects || 0)} detail="Limited historical support" icon={<AlertTriangle size={19} />} />
            <MetricCard label="Post-action outcome recorded" value={`${data.kpis.recorded_outcomes_pct.toFixed(1)}%`} detail="Unknown is not treated as resolved" icon={<ClipboardCheck size={19} />} />
          </div>
          <Notice kind="warning">
            <b>Outcome limitation:</b> most records document an action but not what happened afterwards. A replacement is labelled “corrective action documented”; it is never relabelled as successful without an explicit outcome.
          </Notice>
          <div className="two-column wide-left">
            <Section title="Most recurring defect families" description="Grouped by reviewed component and fault. Position is a distribution rather than a duplicate defect row; research clusters remain unchanged.">
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th>Defect</th><th>Position spread</th><th>Dominant recorded action</th><th className="number">Share</th><th className="number">Orders</th></tr></thead>
                  <tbody>{data.top_recurring.map((item) => (
                    <tr key={item.cluster_id}>
                      <td><strong>{item.problem}</strong><small className="mono-cell">{item.research_clusters || 0} evidence clusters · {item.distinct_families || 0} action families</small></td>
                      <td>{item.positions?.slice(0, 3).map((position) => `${position.position}: ${position.work_orders}`).join(" · ") || "Not recorded"}</td>
                      <td>{item.other_dominant ? <span className="data-quality-flag">Unclassified action text</span> : item.dominant_action || "—"}</td><td className="number">{item.dominant_action_share == null ? "—" : `${(item.dominant_action_share * 100).toFixed(0)}%`}</td>
                      <td className="number"><b>{item.work_orders}</b></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </Section>
            <Section title="Recorded outcome mix" description="Positive, unknown, negative and mixed labels.">
              <OutcomeDonut data={data.outcome_mix} />
            </Section>
          </div>
          <div className="two-column">
            <Section title="Component occurrence" description="Components most often mentioned in the library.">
              <HorizontalBars data={data.component_frequency.slice(0, 10)} dataKey="component" color="#1769c2" height={360} />
            </Section>
            <Section title="Fault-mode occurrence" description="Most frequently extracted fault anchors.">
              <HorizontalBars data={data.fault_frequency.slice(0, 10)} dataKey="fault" color="#d65e68" height={360} />
            </Section>
          </div>
        </>
      )}
    </>
  );
}

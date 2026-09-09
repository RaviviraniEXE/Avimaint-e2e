import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { InsightsResponse, RecurringItem } from "../api/types";
import { HorizontalBars, Matrix } from "../components/Charts";
import { ErrorState, LoadingState, Notice, PageHeader, Section, Tag } from "../components/ui";

type Tab = "register" | "component";
type SortMode = "disagreement" | "frequency" | "least_resolved";

export function InsightsPage() {
  const [tab, setTab] = useState<Tab>("register");
  const [sortMode, setSortMode] = useState<SortMode>("disagreement");
  const [component, setComponent] = useState("");
  const [fault, setFault] = useState("");
  const [selectedCount, setSelectedCount] = useState(0);
  const [data, setData] = useState<InsightsResponse | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    api.insights(component, fault).then((value) => active && setData(value)).catch((reason) => active && setError(reason.message));
    return () => { active = false; };
  }, [component, fault, reload]);

  const defects = useMemo(() => sortDefects(data?.recurring || [], sortMode), [data, sortMode]);
  return (
    <>
      <PageHeader eyebrow="Planner decision support" title="Chronic defects and component history" description="Find recurring defects where recorded actions disagree, then drill into one component. Component aliases are reviewed and position is preserved as a distribution." />
      <div className="tab-strip" role="tablist"><button type="button" role="tab" className={tab === "register" ? "active" : ""} onClick={() => setTab("register")}>Chronic-defect register</button><button type="button" role="tab" className={tab === "component" ? "active" : ""} onClick={() => setTab("component")}>Component drill-down</button></div>
      {error && <ErrorState message={error} retry={() => setReload((value) => value + 1)} />}
      {!data && !error && <LoadingState label="Preparing maintenance patterns…" />}
      {data && tab === "register" && <>
        <Section title="Chronic-defect register" description="Default ranking surfaces uncertainty in the historical response, not merely the most common gasket leaks." action={<label className="inline-select">Sort by<select value={sortMode} onChange={(event) => setSortMode(event.target.value as SortMode)}><option value="disagreement">Most action disagreement</option><option value="frequency">Most frequent</option><option value="least_resolved">Most negative / mixed outcomes</option></select></label>}>
          <div className="table-scroll"><table className="data-table defect-table"><thead><tr><th>Defect</th><th>Position spread</th><th>Recorded response</th><th className="number">Orders</th><th className="number">Outcome record</th></tr></thead><tbody>{defects.slice(0, 80).map((item) => <DefectRow item={item} key={item.cluster_id} />)}</tbody></table></div>
        </Section>
        <Notice><b>Reviewed roll-up:</b> intake → intake gasket; rocker cover → rocker cover gasket. Generic “gasket” remains separate because it is ambiguous. This is a presentation layer only.</Notice>
      </>}
      {data && tab === "component" && <>
        <Section title="Select a component" description="Review the fault and recorded action distribution for one problem-side component.">
          <label className="field-label" htmlFor="component-insight">Component</label><select id="component-insight" className="select" value={component} onChange={(event) => { setComponent(event.target.value); setFault(""); setSelectedCount(0); }}><option value="">All components</option>{data.component_options.map((item) => <option key={item}>{item}</option>)}</select>
        </Section>
        {data.selected_component && data.selected_fault && <Notice><b>Opened matrix cell:</b> {data.selected_component} · {data.selected_fault} · {selectedCount} work orders. The action chart is filtered to this exact component–fault context. <button className="link-button" type="button" onClick={() => { setFault(""); setSelectedCount(0); }}>Clear fault filter</button></Notice>}
        <div className="two-column"><Section title="Recorded action families" description={data.selected_fault ? `Historical action distribution for ${data.selected_component} · ${data.selected_fault}.` : "Counts describe historical records; they are not a technical correctness probability."}><HorizontalBars data={data.component_actions} dataKey="action_family" color="#15936c" height={420} /></Section><Section title="Component × fault context" description="Select a non-zero cell to open its exact historical action distribution."><Matrix {...data.matrix} onSelect={(selectedComponent, selectedFault, value) => { setComponent(selectedComponent); setFault(selectedFault); setSelectedCount(value); }} /></Section></div>
      </>}
      {data && <p className="page-note">{data.note}</p>}
    </>
  );
}

function sortDefects(items: RecurringItem[], mode: SortMode) {
  return [...items].sort((a, b) => {
    if (mode === "frequency") return b.work_orders - a.work_orders || a.problem.localeCompare(b.problem);
    if (mode === "least_resolved") return (b.negative_outcomes || 0) - (a.negative_outcomes || 0) || b.work_orders - a.work_orders;
    return (a.dominant_action_share ?? 1) - (b.dominant_action_share ?? 1) || (b.distinct_families || 0) - (a.distinct_families || 0) || b.work_orders - a.work_orders;
  });
}

function DefectRow({ item }: { item: RecurringItem }) {
  const positionText = item.positions?.slice(0, 4).map((entry) => `${entry.position}: ${entry.work_orders}`).join(" · ") || "Not recorded";
  return <tr><td><strong>{item.problem}</strong><small className="mono-cell">{item.research_clusters || 0} independent evidence clusters</small></td><td>{positionText}</td><td>{item.other_dominant ? <Tag tone="amber">Unclassified action text</Tag> : <><b>{item.dominant_action || "—"}</b><small className="mono-cell">{item.dominant_action_share == null ? "" : `${(item.dominant_action_share * 100).toFixed(0)}% dominant · `}{item.distinct_families || 0} families</small></>}</td><td className="number"><b>{item.work_orders}</b></td><td className="number"><span className="positive-text">{item.positive_outcomes || 0} resolved</span><small className="mono-cell negative-text">{item.negative_outcomes || 0} did not resolve / mixed</small></td></tr>;
}

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { GraphResponse } from "../api/types";
import { KnowledgeNetwork } from "../components/KnowledgeNetwork";
import { EmptyState, ErrorState, LoadingState, Notice, PageHeader, Section } from "../components/ui";

export function KnowledgeGraphPage() {
  const [focus, setFocus] = useState("intake gasket");
  const [data, setData] = useState<GraphResponse | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setError("");
    api.graph({ topComponents: 10, topFaults: 12, minEdge: 1, focusComponent: focus }).then((value) => active && setData(value)).catch((reason) => active && setError(reason.message));
    return () => { active = false; };
  }, [focus]);
  const faults = data?.nodes.filter((node) => node.kind === "fault").sort((a, b) => b.count - a.count) || [];
  const actions = data?.nodes.filter((node) => node.kind === "action").sort((a, b) => b.count - a.count) || [];
  return (
    <>
      <PageHeader eyebrow="Component reference" title="What else is recorded for this component?" description="Choose a problem-side component to review its fault context and recorded response families. This page is descriptive; Diagnose applies the stricter action-matching policy." />
      <Section title="Component" description="Reviewed presentation aliases are used in this reference view."><select className="select" value={focus} onChange={(event) => setFocus(event.target.value)}>{data?.component_options.map((item) => <option key={item}>{item}</option>)}</select></Section>
      <Notice><b>No causal or recommendation claim:</b> these counts show co-occurrence in historical work orders. An action-family node does not mean that action targeted, caused, or resolved the selected component.</Notice>
      {error && <ErrorState message={error} />}
      {!data && !error && <LoadingState label="Loading component history…" />}
      {data && <>
        <div className="two-column"><Section title="Recorded fault context" description={`${data.scope?.records.toLocaleString() || 0} work orders in the selected component scope.`}>{faults.length ? <div className="reference-list">{faults.map((item) => <div key={item.id}><span>{item.label}</span><b>{item.count.toLocaleString()}</b></div>)}</div> : <EmptyState title="No fault context" detail="No structured faults were available for this component." />}</Section><Section title="Recorded response families" description="Family counts in the same problem-side scope; inspect Diagnose before treating any as an option.">{actions.length ? <div className="reference-list">{actions.map((item) => <div key={item.id}><span>{item.label}</span><b>{item.count.toLocaleString()}</b></div>)}</div> : <EmptyState title="No classified actions" detail="No supported action family was available in this scope." />}</Section></div>
        <details className="result-disclosure"><summary>Open co-occurrence network</summary><Section className="network-panel" title={`Historical context: ${data.focus_component}`} description={data.note}>{data.nodes.length ? <KnowledgeNetwork nodes={data.nodes} edges={data.edges} /> : <EmptyState title="No network available" detail="Choose another component." />}</Section></details>
      </>}
    </>
  );
}

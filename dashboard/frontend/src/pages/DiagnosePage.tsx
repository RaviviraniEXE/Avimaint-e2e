import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Braces, Check, ClipboardPlus, Copy, FileSearch, Flag, Plane, Printer, Search, ShieldCheck, ThumbsUp, Wrench } from "lucide-react";
import { api } from "../api/client";
import type { CaseEvidence, CaseRecord, DiagnoseResponse, Entity, Recommendation, Relation, Strategy } from "../api/types";
import { Definition, ErrorState, EvidenceBadge, Notice, PageHeader, Section, Tag } from "../components/ui";
import { getEntityText, getEntityType, loadWatchlist, percent, recommendationToWatchlist, saveWatchlist, score } from "../utils";

const examples = [
  { label: "Intake leak", query: "Number 2 intake leaking." },
  { label: "Low compression", query: "Left-hand engine number 2 cylinder has low compression." },
  { label: "Rough running", query: "Engine running rough." },
  { label: "Specific gasket", query: "Number 4 intake gasket leaking." },
];

function initialQuery() {
  return new URLSearchParams(window.location.search).get("q") || "Number 2 intake leaking.";
}

function initialParameter(name: string) { return new URLSearchParams(window.location.search).get(name) || ""; }

export function DiagnosePage() {
  const [query, setQuery] = useState(initialQuery);
  const [response, setResponse] = useState<DiagnoseResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [componentOverride, setComponentOverride] = useState(() => initialParameter("component"));
  const [faultOverride, setFaultOverride] = useState(() => initialParameter("fault"));
  const [locationOverride, setLocationOverride] = useState(() => initialParameter("location"));
  const queryRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const shortcut = (event: globalThis.KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const editing = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.tagName === "SELECT";
      if (event.key === "/" && !editing) {
        event.preventDefault();
        queryRef.current?.focus();
      }
      if (event.key === "Escape" && document.activeElement === queryRef.current) {
        setQuery("");
        setResponse(null);
      }
    };
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, []);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).has("q")) void submit();
  }, []);

  async function submit(event?: React.FormEvent) {
    event?.preventDefault();
    if (!query.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const value = await api.diagnose(query.trim(), undefined, { component: componentOverride, fault: faultOverride, location: locationOverride });
      setResponse(value);
      const parameters = new URLSearchParams({ q: query.trim() });
      if (componentOverride.trim()) parameters.set("component", componentOverride.trim());
      if (faultOverride.trim()) parameters.set("fault", faultOverride.trim());
      if (locationOverride.trim()) parameters.set("location", locationOverride.trim());
      window.history.replaceState(null, "", `${window.location.pathname}?${parameters.toString()}#/diagnose`);
    } catch (reason) {
      setResponse(null);
      setError(reason instanceof Error ? reason.message : "Diagnosis failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader eyebrow="Historical maintenance evidence" title="Diagnose a reported problem" description="Enter the problem only. The system compares the component and fault, keeps position-specific support visible, and presents every recorded action target as an independent option." />
      <form className="diagnose-form" onSubmit={submit}>
        <div className="query-box">
          <Plane size={23} />
          <textarea ref={queryRef} aria-label="Maintenance problem" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); } }} placeholder="e.g. LEFT MAGNETO RPM DROP ON RUN UP" rows={3} maxLength={5000} />
          <button className="button primary diagnose-button" type="submit" disabled={!query.trim() || busy}>{busy ? <><span className="button-spinner" /> Matching…</> : <><Search size={18} /> Find evidence</>}</button>
        </div>
        <div className="example-row"><span>Examples</span>{examples.map((item) => <button key={item.label} type="button" onClick={() => setQuery(item.query)}>{item.label}</button>)}<small><kbd>/</kbd> focus · <kbd>Enter</kbd> run · <kbd>Esc</kbd> clear</small></div>
        <details className="anchor-correction"><summary>Correct extracted anchors (optional)</summary><p>Use only when the interpretation is wrong. Corrections change matching for this query but never rewrite the frozen records.</p><div className="anchor-correction-grid"><label>Component<input value={componentOverride} onChange={(event) => setComponentOverride(event.target.value)} placeholder="e.g. intake gasket" /></label><label>Fault<input value={faultOverride} onChange={(event) => setFaultOverride(event.target.value)} placeholder="e.g. leak" /></label><label>Position<input value={locationOverride} onChange={(event) => setLocationOverride(event.target.value)} placeholder="e.g. number 2" /></label></div></details>
      </form>
      <Notice kind="warning" title="Operational boundary">Results are historical planning evidence—not a maintenance instruction, airworthiness finding, regulatory approval, or probability of technical correctness.</Notice>
      {busy && <AnalysisProgress />}
      {error && <ErrorState message={error} retry={() => void submit()} />}
      {!busy && response && <DiagnoseResult response={response} />}
      {!busy && <details className="result-disclosure lookup-disclosure"><summary>Look up a historical work order by ID</summary><WorkOrderLookup /></details>}
    </>
  );
}

function AnalysisProgress() {
  return <div className="analysis-progress" role="status"><div className="radar"><span /><span /><i /></div><div><strong>Matching historical evidence</strong><p>Searching the frozen TRAIN library, matching component and fault, and separating support at this position from other positions.</p></div></div>;
}

function WorkOrderLookup() {
  const [ident, setIdent] = useState("");
  const [record, setRecord] = useState<CaseRecord | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function lookup(event: React.FormEvent) {
    event.preventDefault();
    if (!ident.trim()) return;
    setBusy(true); setError(""); setRecord(null);
    try { setRecord((await api.case(ident)).case); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Work order lookup failed."); }
    finally { setBusy(false); }
  }
  return (
    <Section className="lookup-panel" title="Look up a historical work order" description="Open one source record directly by its work-order identifier.">
      <form className="lookup-form" onSubmit={lookup}><input value={ident} onChange={(event) => setIdent(event.target.value)} placeholder="Work order ID, e.g. 100742" aria-label="Work order ID" /><button className="button secondary" type="submit" disabled={busy || !ident.trim()}><FileSearch size={17} />{busy ? "Looking up…" : "Open record"}</button></form>
      {error && <p className="lookup-error">{error}</p>}
      {record && <CaseLookupResult record={record} />}
    </Section>
  );
}

function CaseLookupResult({ record }: { record: CaseRecord }) {
  return (
    <article className="lookup-result">
      <div className="lookup-result-head"><div><small>WORK ORDER {record.ident}</small><h3>{record.problem}</h3></div><Tag tone="slate">{record.split.toUpperCase()} record</Tag></div>
      <p><b>Recorded action:</b> {record.action || "No action text recorded"}</p>
      <div className="source-facts"><span>{record.action_kind}</span><span>{record.outcome_label}</span><span>{[record.component, record.fault, ...record.locations].filter(Boolean).join(" · ")}</span></div>
      {(record.problem_may_be_truncated || record.action_may_be_truncated) && <p className="source-warning">The source appears truncated; missing words were not inferred.</p>}
    </article>
  );
}

function DiagnoseResult({ response }: { response: DiagnoseResponse }) {
  const result = response.result;
  return (
    <div className="diagnose-results">
      <RecommendationView result={result} />
      <details className="result-disclosure"><summary>What the system matched</summary><Interpretation result={result} /></details>
      <CasesSection title="Supporting historical work orders" description="One representative record per independent evidence cluster for the most recorded action target." cases={result.recommended_cases} />
      {result.unclassified_action_evidence && result.unclassified_action_evidence.length > 0 && <CasesSection title="Unclassified recorded actions" description="These matching records contain action text that could not be assigned to a supported family. They are data-quality evidence, not suggestions." cases={result.unclassified_action_evidence} />}
      <details className="result-disclosure"><summary>Broader nearest cases and technical provenance</summary>
        <CasesSection title="Broader nearest historical cases" description="Similarity references only. Different components or faults never contribute to the action options above." cases={result.nearest_cases} />
        <Section title="Technical provenance" description="Frozen research assets and operational safeguards used for this request.">
          <div className="provenance-grid"><Definition term="User input"><code>{result.query}</code></Definition><Definition term="Readable interpretation"><code>{result.normalized_interpretation || result.query}</code></Definition><Definition term="Canonical retrieval key"><code>{result.model_input || "Not reported"}</code></Definition><Definition term="Evidence library">{response.meta.candidate_split.toUpperCase()} only</Definition><Definition term="Retrieval base">{response.meta.rq4_base}</Definition><Definition term="Query structure">{result.query_structure_source?.replaceAll("_", " ")}</Definition></div>
          <div className="warning-list">{[result.normalization_warning, result.semantic_warning, result.partial_structure_warning].filter(Boolean).map((warning) => <p key={warning}><AlertTriangle size={16} />{warning}</p>)}</div>
        </Section>
      </details>
    </div>
  );
}

function Interpretation({ result }: { result: Recommendation }) {
  const anchors = [...result.model_components, ...result.model_faults, ...result.semantic_locations];
  return (
    <Section className="interpretation-card">
      <div className="interpretation-title"><div><span className="eyebrow">Protected query interpretation</span><h2>{result.normalized_interpretation || result.query}</h2></div><div className="tag-row"><Tag tone="green">Component + fault matched</Tag>{result.manual_anchor_override && <Tag tone="amber">Engineer-corrected anchors</Tag>}</div></div>
      <div className="anchor-row"><b>Matched anchors</b>{anchors.length ? anchors.map((item, index) => <Tag key={`${item}-${index}`}>{item.replace("num_", "number ")}</Tag>) : <span>No usable anchor extracted</span>}</div>
      <details className="details-panel"><summary><Braces size={17} /> Entities and relations</summary><StructurePayload entities={result.entities} relations={result.relations} /></details>
      <details className="details-panel"><summary><FileSearch size={17} /> Frozen RQ4 representation</summary><StructurePayload entities={result.rq4_entities} relations={result.rq4_relations} /></details>
    </Section>
  );
}

function RecommendationView({ result }: { result: Recommendation }) {
  const [added, setAdded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<"" | "sending" | "useful" | "needs_review" | "error">("");
  const actionSet = result.action_set?.length ? result.action_set : result.strategies;
  const canPromote = Boolean(result.structured_sentence && !result.abstain);
  function addToPlanning() { saveWatchlist([recommendationToWatchlist(result), ...loadWatchlist()].slice(0, 100)); window.dispatchEvent(new Event("avimaint-watchlist")); setAdded(true); }
  async function copyLink() { try { await navigator.clipboard.writeText(window.location.href); setCopied(true); window.setTimeout(() => setCopied(false), 1800); } catch { setCopied(false); } }
  async function sendFeedback(rating: "useful" | "needs_review") { setFeedback("sending"); try { await api.feedback(result, rating); setFeedback(rating); } catch { setFeedback("error"); } }
  return (
    <Section className={`decision-card ${result.badge}`}>
      <div className="decision-top"><EvidenceBadge badge={result.badge} /><div className="decision-metrics">{result.query_position_specified === false ? <span><b>{result.query_position_unspecified_match_clusters || 0}</b> events · query position not specified</span> : <><span><b>{result.same_position_match_clusters || 0}</b> events at this position</span><span><b>{result.other_position_match_clusters || 0}</b> at other positions</span></>}<span><b>{result.comparable_action_cases || 0}</b> comparable action records</span></div></div>
      {actionSet.length ? <div className="action-set-block">
        <div className="primary-action-heading"><Wrench size={24} /><div><small>MATCHING HISTORICAL ACTION OPTIONS</small><h2>{actionSet[0].sentence}</h2><p>Most frequently documented target-specific action. Alternatives remain separate because the history does not record a safe action sequence.</p></div></div>
        <div className="professional-action-set">{actionSet.map((strategy, index) => <ActionEvidenceCard strategy={strategy} primary={index === 0} comparableCases={result.comparable_action_cases || 0} queryPositionSpecified={result.query_position_specified !== false} key={`${strategy.family}-${strategy.action_target}-${index}`} />)}</div>
        <p className="action-set-note">{result.action_set_note}</p>
      </div> : <div className="abstention"><ShieldCheck size={27} /><div><h2>No classified matching action found</h2><p>{result.headline_reason}</p></div></div>}
      {result.badge === "limited" && <Notice kind="warning"><b>Limited evidence.</b> The option remains visible because at least one independent matching event exists.</Notice>}
      <div className="decision-actions">{canPromote && <button className="button secondary" type="button" onClick={addToPlanning} disabled={added}>{added ? <><Check size={17} /> Added to planning</> : <><ClipboardPlus size={17} /> Add to planning</>}</button>}<button className="button ghost" type="button" onClick={() => void copyLink()}><Copy size={17} /> {copied ? "Link copied" : "Copy result link"}</button><button className="button ghost" type="button" onClick={() => window.print()}><Printer size={17} /> Print evidence</button></div>
      <div className="feedback-row"><span>Was this historical evidence useful for planning?</span><button type="button" disabled={feedback === "sending" || feedback === "useful" || feedback === "needs_review"} onClick={() => void sendFeedback("useful")}><ThumbsUp size={16} /> Useful</button><button type="button" disabled={feedback === "sending" || feedback === "useful" || feedback === "needs_review"} onClick={() => void sendFeedback("needs_review")}><Flag size={16} /> Needs review</button>{feedback === "useful" || feedback === "needs_review" ? <small>Recorded as a usability judgment—not technical correctness.</small> : feedback === "error" ? <small className="negative-text">Could not record feedback.</small> : null}</div>
    </Section>
  );
}

function ActionEvidenceCard({ strategy, primary, comparableCases, queryPositionSpecified }: { strategy: Strategy; primary: boolean; comparableCases: number; queryPositionSpecified: boolean }) {
  const otherPositions = (strategy.other_positions || []).map((item) => `${item.position}: ${item.cases}`).join(" · ");
  const share = comparableCases ? strategy.case_count / comparableCases : strategy.share_of_comparable_cases || 0;
  return (
    <article className={`action-evidence-card ${strategy.tier === "single_case" ? "limited" : ""}`}>
      <div className="action-card-head"><div><small>{primary ? "MOST RECORDED" : strategy.tier === "single_case" ? "LIMITED · ONE EVENT" : "ALSO RECORDED"}</small><h3>{strategy.sentence}</h3></div><div className="tag-row">{primary && <Tag tone="green">Primary evidence pattern</Tag>}{Boolean(strategy.full_structure_support_clusters) && <Tag>{strategy.full_structure_support_clusters} exact structure event{strategy.full_structure_support_clusters === 1 ? "" : "s"}</Tag>}</div></div>
      <div className="action-facts"><div><span>Frequency</span><b>{strategy.case_count} of {comparableCases || strategy.case_count} comparable records ({percent(share)})</b></div><div><span>Independent support</span><b>{strategy.support_clusters} event{strategy.support_clusters === 1 ? "" : "s"}</b></div><div><span>Position</span><b>{queryPositionSpecified ? <>{strategy.same_position_cases || 0} here · {strategy.other_position_cases || 0} elsewhere{strategy.position_not_recorded_cases ? ` · ${strategy.position_not_recorded_cases} not recorded` : ""}</> : <>{strategy.query_position_unspecified_cases || strategy.case_count} records · query position not specified</>}</b></div><div><span>Outcome documentation</span><b>{strategy.outcome_positive} resolved · {strategy.outcome_unknown} not recorded · {strategy.outcome_negative} did not resolve/mixed</b></div></div>
      {queryPositionSpecified && otherPositions && <p className="position-spread"><b>Other recorded positions:</b> {otherPositions}</p>}
      <p className="action-kind">{strategy.category === "assessment" ? "Assessment/check documented" : "Corrective action documented"}. “Outcome not recorded” is not treated as success or failure.</p>
      {strategy.examples.length > 0 && <details><summary>Source work orders</summary>{strategy.examples.map((example) => <div className="strategy-example" key={`${example.ident}-${example.action}`}><b>{example.ident}</b><span>{example.action}</span><em>{outcomeLabel(example.outcome)}</em></div>)}</details>}
    </article>
  );
}

function outcomeLabel(outcome?: string) { if (outcome === "positive") return "resolved recorded"; if (outcome === "negative" || outcome === "mixed") return "did not resolve / mixed"; return "outcome not recorded"; }

function CasesSection({ title, description, cases }: { title: string; description: string; cases: CaseEvidence[] }) {
  if (!cases.length) return null;
  return <Section title={title} description={description}><div className="case-list">{cases.map((item, index) => <CaseCard item={item} rank={index + 1} key={`${item.ident}-${item.cluster_id}-${index}`} />)}</div></Section>;
}

function CaseCard({ item, rank }: { item: CaseEvidence; rank: number }) {
  return (
    <details className="case-card"><summary><span className="case-rank">{rank}</span><div className="case-summary"><b>{item.problem}</b><span>{item.action_kind || `${item.action_family} action documented`} · {item.outcome_label || outcomeLabel(item.outcome)} · {item.match_level || "nearest case"}</span></div><span className="case-score">{score(item.score)}</span></summary><div className="case-detail">{(item.problem_may_be_truncated || item.action_may_be_truncated) && <p className="source-warning">The source appears truncated. Missing words were not inferred or completed.</p>}<div><span>Recorded action</span><p>{item.action || "No action text recorded"}</p></div>{item.problem_raw && item.problem_raw !== item.problem && <div><span>Original problem text</span><p>{item.problem_raw}</p></div>}{item.action_raw && item.action_raw !== item.action && <div><span>Original action text</span><p>{item.action_raw}</p></div>}<dl><Definition term="Source record">{item.ident}</Definition><Definition term="Evidence cluster">{item.cluster_id}</Definition><Definition term="Relative text score">{score(item.text_score)}</Definition><Definition term="Match basis">{item.match_level || "broader nearest case"}</Definition></dl></div></details>
  );
}

function StructurePayload({ entities, relations }: { entities: Entity[]; relations: Relation[] }) {
  const entityName = (endpoint: Relation["head"]) => typeof endpoint === "number" ? getEntityText(entities[endpoint] || {}) : endpoint && typeof endpoint === "object" ? getEntityText(endpoint) : "?";
  return <div className="structure-grid"><div><h4>Entities · {entities.length}</h4>{entities.length ? <div className="entity-list">{entities.map((entity, index) => <span key={index}><b>{getEntityType(entity)}</b>{getEntityText(entity)}</span>)}</div> : <p>No usable entities returned.</p>}</div><div><h4>Relations · {relations.length}</h4>{relations.length ? <div className="relation-list">{relations.map((relation, index) => <span key={index}><b>{String(relation.type ?? relation.label ?? "RELATION")}</b>{entityName(relation.head)} → {entityName(relation.tail)}{relation.source === "deterministic_schema_adapter" ? " · adapter" : " · frozen SpERT"}</span>)}</div> : <p>No relation was available for this wording.</p>}</div></div>;
}

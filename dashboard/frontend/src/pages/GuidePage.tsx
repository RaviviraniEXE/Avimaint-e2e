import { BookOpenCheck, CircleHelp, GitBranch, Search, ShieldCheck } from "lucide-react";
import { Notice, PageHeader, Section } from "../components/ui";

export function GuidePage() {
  return (
    <>
      <PageHeader eyebrow="How to interpret the system" title="AviMaint-DSS guide" description="A concise reference for the frozen Selective representation, problem-only retrieval, evidence tiers, and safe use of historical maintenance evidence." />
      <div className="guide-grid">
        <Section title="Diagnose workflow">
          <ol className="flow-steps">
            <li><span>1</span><div><Search size={19} /><b>Problem text only</b><p>The query action is never used to retrieve supporting cases.</p></div></li>
            <li><span>2</span><div><GitBranch size={19} /><b>One Selective representation</b><p>The dashboard uses the same Selective normalized corpus and precomputed Selective SpERT structure as the final RQ4/RQ5 run.</p></div></li>
            <li><span>3</span><div><BookOpenCheck size={19} /><b>Component and fault must match</b><p>Position then separates evidence from this position, other positions, and records where position was not documented.</p></div></li>
            <li><span>4</span><div><ShieldCheck size={19} /><b>Target-specific actions</b><p>Different replaced or assessed components remain separate options. One-event actions stay visible as Limited.</p></div></li>
          </ol>
        </Section>
        <Section title="Evidence tiers">
          <div className="tier-list">
            <div className="strong"><b>Strong historical evidence</b><p>At least three supporting events at this position, or at least six supporting events across disclosed positions.</p></div>
            <div className="moderate"><b>Moderate historical evidence</b><p>At least two supporting events at this position, or three to five across disclosed positions.</p></div>
            <div className="limited"><b>Limited historical evidence</b><p>One or two supporting events below the moderate threshold. Even one event remains visible.</p></div>
            <div className="exploratory"><b>Exploratory evidence</b><p>Related historical evidence exists but does not justify a primary action.</p></div>
            <div className="abstain"><b>Nearest cases only</b><p>The system abstains and exposes cases for manual inspection.</p></div>
          </div>
        </Section>
      </div>
      <Section title="What every Diagnose result exposes" description="Use these fields together; no single score replaces engineering review.">
        <div className="guide-features">
          <div><b>Raw and normalized text</b><p>Normalized text drives readable display; raw text remains available for source verification.</p></div>
          <div><b>Entities and relations</b><p>Shows structured components, faults, locations, observations, and their indexed connections.</p></div>
          <div><b>Two grouping levels</b><p>Leakage groups protect the research split; exact evidence clusters control voting. Readable dashboard groups never change either one.</p></div>
          <div><b>Position strata</b><p>Counts at this position and other positions are shown separately; location is not a silent hard gate.</p></div>
          <div><b>Source work orders</b><p>Every displayed action stays linked to record and cluster identifiers.</p></div>
          <div><b>Outcome documentation</b><p>Resolved and did-not-resolve labels are reported when present. Unknown means the post-action outcome was not recorded.</p></div>
        </div>
      </Section>
      <Notice kind="warning" title="The system does not authorise work">
        AviMaint-DSS does not select approved maintenance data, determine airworthiness, certify applicability, generate a maintenance procedure, approve parts, satisfy regulatory requirements, or release an aircraft to service.
      </Notice>
      <Section title="Recommended review sequence">
        <div className="review-sequence"><span>1. Confirm component, fault and position</span><span>2. Compare target-specific action options</span><span>3. Check this-position versus other-position support</span><span>4. Inspect outcome documentation</span><span>5. Verify source work orders</span><span>6. Consult current approved data</span></div>
      </Section>
      <div className="help-callout"><CircleHelp size={24} /><div><b>When evidence feels too confident</b><p>Do not act on it. Capture the query and visible provenance, then include it in the end-to-end diagnostic review.</p></div></div>
    </>
  );
}

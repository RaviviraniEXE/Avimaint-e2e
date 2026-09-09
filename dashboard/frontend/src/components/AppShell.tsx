import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import {
  Activity,
  BarChart3,
  BookOpen,
  ClipboardList,
  Gauge,
  GitBranch,
  Menu,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import type { HealthResponse } from "../api/types";

export type PageKey =
  | "overview"
  | "diagnose"
  | "insights"
  | "knowledge-graph"
  | "planning"
  | "evaluation"
  | "guide";

const nav: Array<{ key: PageKey; label: string; short: string; icon: ComponentType<{ size?: number }>; groupStart?: boolean }> = [
  { key: "overview", label: "Overview", short: "Overview", icon: Gauge },
  { key: "diagnose", label: "Diagnose", short: "Diagnose", icon: Search },
  { key: "planning", label: "Planning", short: "Planning", icon: ClipboardList },
  { key: "insights", label: "Chronic Defects", short: "Defects", icon: BarChart3 },
  { key: "knowledge-graph", label: "Component History", short: "History", icon: GitBranch, groupStart: true },
  { key: "evaluation", label: "Research Evidence", short: "Research", icon: Activity },
  { key: "guide", label: "Guide", short: "Guide", icon: BookOpen },
];

export function AppShell({
  page,
  onNavigate,
  health,
  children,
}: {
  page: PageKey;
  onNavigate: (page: PageKey) => void;
  health: HealthResponse | null;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [healthOpen, setHealthOpen] = useState(false);
  useEffect(() => setOpen(false), [page]);

  const ready = health?.status === "ready" && health.frontend?.ready;
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="nav-frame">
          <button className="mobile-menu" type="button" onClick={() => setOpen(!open)} aria-label="Open navigation">
            {open ? <X size={22} /> : <Menu size={22} />}
          </button>
          <button className="brand" type="button" onClick={() => onNavigate("overview")}>
            <span className="brand-mark"><ShieldCheck size={22} /></span>
            <span>
              <b>AviMaint</b><em>DSS</em>
              <small>Evidence-grounded planning support</small>
            </span>
          </button>
          <nav className={`desktop-nav ${open ? "open" : ""}`} aria-label="Primary navigation">
            {nav.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  type="button"
                  key={item.key}
                  className={`${page === item.key ? "active" : ""}${item.groupStart ? " reference-start" : ""}`}
                  onClick={() => onNavigate(item.key)}
                >
                  <Icon size={17} />
                  <span className="full-label">{item.label}</span>
                  <span className="short-label">{item.short}</span>
                </button>
              );
            })}
          </nav>
          <button
            className={`system-status ${ready ? "ready" : "degraded"}`}
            type="button"
            onClick={() => setHealthOpen(!healthOpen)}
            aria-expanded={healthOpen}
          >
            <span className="status-dot" />
            <span>{ready ? "System ready" : health ? "Degraded" : "Connecting"}</span>
          </button>
          {healthOpen && (
            <div className="health-popover">
              <div className="health-heading">
                <strong>Runtime services</strong>
                <span>API {health?.api_version || "…"}</span>
              </div>
              <HealthRow label="Selective corpus" ready={health?.raw_spert.ready} />
              <HealthRow label="Protected query adapter" ready={health?.normalization.ready} />
              <HealthRow label="Frozen SpERT structure" ready={health?.semantic_spert.ready} />
              <HealthRow label="RQ5 calibrator" ready={health?.rq5_calibrator.ready} />
              <HealthRow label="Dashboard frontend" ready={health?.frontend.ready} />
              <p>The hosted artifact profile uses frozen model outputs. Neural weights are optional and are not loaded by default.</p>
            </div>
          )}
        </div>
      </header>

      <main className="main-content">{children}</main>

      <footer className="footer">
        <div className="footer-project">
          <strong>AviMaint-DSS v8.3.2</strong>
          <span>Evidence-grounded planning support for historical maintenance work orders</span>
        </div>
        <div className="footer-thesis">
          <span>Master’s thesis contribution</span>
          <strong>Ravi Virani</strong>
          <small>Development and Evaluation of an NLP-Based Concept for Structured Information Extraction and Planning Support in Maintenance Work Orders</small>
        </div>
        <div className="footer-institution">
          <strong>Deggendorf Institute of Technology</strong>
          <span>Faculty of Applied Natural Sciences and Industrial Engineering</span>
          <span>Applied AI for Digital Production Management</span>
          <small>Academic supervision: Prof. Dr.-Ing. Ralph Hensel-Unger</small>
        </div>
        <p className="footer-boundary">Decision support only · 6,169 frozen work orders · source dates unavailable · post-action outcome recorded in 9.8% · verify against current authorised documentation.</p>
      </footer>
    </div>
  );
}

function HealthRow({ label, ready, optional = false }: { label: string; ready?: boolean; optional?: boolean }) {
  return (
    <div className="health-row">
      <span className={ready ? "ok" : optional ? "optional" : "bad"} />
      <b>{label}</b>
      <small>{ready ? "ready" : optional ? "fallback available" : "required"}</small>
    </div>
  );
}

export type ServiceHealth = {
  ready: boolean;
  error?: string;
  metadata?: Record<string, unknown>;
};

export type HealthResponse = {
  status: "ready" | "degraded" | string;
  api_version: string;
  rq4_base: string;
  candidate_split: string;
  critical_ready: boolean;
  phase2_compound_decomposition: boolean;
  phase3_limited_evidence: boolean;
  raw_spert: ServiceHealth;
  normalization: ServiceHealth;
  semantic_spert: ServiceHealth;
  rq5_calibrator: ServiceHealth & { status?: string };
  frontend: {
    ready: boolean;
    version: string;
    expected_version: string;
    mode: string;
    url: string;
  };
  runtime_model_lock?: Record<string, unknown>;
};

export type Kpis = {
  work_orders: number;
  unique_problems: number;
  problem_clusters: number;
  components_tracked: number;
  action_families: number;
  recurring_faults: number;
  recorded_outcomes_pct: number;
  spert_backed: boolean;
  most_recurring_defect?: string;
  most_recurring_defect_orders?: number;
  multi_action_clusters?: number;
  repeated_clusters?: number;
  multi_action_cluster_pct?: number;
  single_record_defects?: number;
};

export type RecurringItem = {
  cluster_id: string;
  problem: string;
  component: string;
  fault: string;
  work_orders: number;
  top_action?: string;
  dominant_action?: string;
  positive_outcomes?: number;
  negative_outcomes?: number;
  outcome_unknown?: number;
  research_clusters?: number;
  dominant_action_share?: number;
  distinct_families?: number;
  other_dominant?: boolean;
  recorded_outcome_rate?: number;
  positive_rate_among_recorded?: number | null;
  positions?: Array<{ position: string; work_orders: number }>;
};

export type FrequencyItem = {
  component?: string;
  fault?: string;
  action_family?: string;
  outcome?: string;
  work_orders: number;
  share_pct?: number;
  cumulative_pct?: number;
};

export type OverviewResponse = {
  kpis: Kpis;
  top_recurring: RecurringItem[];
  component_frequency: FrequencyItem[];
  fault_frequency: FrequencyItem[];
  action_frequency: FrequencyItem[];
  outcome_mix: FrequencyItem[];
  note: string;
};

export type Entity = {
  type?: string;
  label?: string;
  text?: string;
  phrase?: string;
  start?: number;
  end?: number;
  score?: number;
  [key: string]: unknown;
};

export type Relation = {
  type?: string;
  label?: string;
  head?: number | Entity;
  tail?: number | Entity;
  score?: number;
  [key: string]: unknown;
};

export type CaseEvidence = {
  ident: string;
  problem: string;
  action: string;
  problem_raw?: string;
  action_raw?: string;
  problem_may_be_truncated?: boolean;
  action_may_be_truncated?: boolean;
  action_family: string;
  outcome: string;
  outcome_label?: string;
  action_kind?: string;
  cluster_id: string;
  score: number;
  text_score: number;
  structure_score: number;
  channels?: Record<string, number>;
  match_level?: string;
};

export type Strategy = {
  family: string;
  action_target?: string;
  sentence: string;
  meaning: string;
  support_clusters: number;
  matching_clusters?: number;
  same_position_clusters?: number;
  other_position_clusters?: number;
  position_not_recorded_clusters?: number;
  query_position_unspecified_clusters?: number;
  full_structure_support_clusters?: number;
  case_count: number;
  same_position_cases?: number;
  other_position_cases?: number;
  position_not_recorded_cases?: number;
  query_position_unspecified_cases?: number;
  other_positions?: Array<{ position: string; cases: number }>;
  share_of_comparable_cases?: number;
  outcome_positive: number;
  outcome_negative: number;
  outcome_unknown: number;
  examples: Array<{ ident: string; action: string; outcome?: string; source_may_be_truncated?: boolean }>;
  is_primary: boolean;
  tier: "corroborated" | "single_case" | string;
  role?: "primary" | "supported_alternative" | "limited_alternative" | "assessment_option" | string;
  category?: "corrective" | "assessment" | string;
};

export type Subproblem = {
  index: number;
  title: string;
  query: string;
  component: string;
  location: string;
  issue: string;
  issue_type: string;
  relation_score: number;
  recommendation: Recommendation;
};

export type Recommendation = {
  query: string;
  components: string[];
  faults: string[];
  badge: "strong" | "moderate" | "limited" | "exploratory" | "abstain" | string;
  lens: string;
  headline_action: string;
  headline_reason: string;
  support_clusters: number;
  structured_sentence: string;
  action_set_summary?: string;
  action_set?: Strategy[];
  action_set_sequence_supported?: boolean;
  action_set_note?: string;
  strategies: Strategy[];
  recommended_cases: CaseEvidence[];
  alternatives: unknown[];
  nearest_cases: CaseEvidence[];
  negative_evidence: CaseEvidence[];
  unclassified_action_evidence?: CaseEvidence[];
  comparable_action_cases?: number;
  structure_source: string;
  entities: Entity[];
  relations: Relation[];
  family_evidence_margin: number;
  retrieval_margin: number;
  anchor_coverage: number;
  abstain: boolean;
  evidence_family: string;
  base_top_score: number;
  evidence_tier: string;
  evidence_note: string;
  historical_agreement_probability: number | null;
  calibration_source: string;
  reranker_used: boolean;
  candidate_split: string;
  model_components: string[];
  model_faults: string[];
  derived_components: string[];
  derived_faults: string[];
  target_location: string;
  partial_structure_warning: string;
  model_input: string;
  input_adapter: string;
  input_adapted: boolean;
  normalized_interpretation: string;
  normalization_model_input: string;
  normalization_method: string;
  normalization_warning: string;
  normalization_model: string;
  semantic_branch_used: boolean;
  semantic_status: string;
  semantic_warning: string;
  semantic_entities: Entity[];
  semantic_relations: Relation[];
  semantic_components: string[];
  semantic_faults: string[];
  semantic_locations: string[];
  rq4_entities: Entity[];
  rq4_relations: Relation[];
  rq4_components: string[];
  rq4_faults: string[];
  rq4_structure_source: string;
  rq4_live_validated: boolean;
  compound_detected: boolean;
  decomposition_source: string;
  subproblems: Subproblem[];
  operational_match_policy?: string;
  matching_signature?: { component: string; fault: string; locations: string[] };
  exact_match_clusters?: number;
  same_position_match_clusters?: number;
  other_position_match_clusters?: number;
  full_structure_match_clusters?: number;
  relation_match_evaluated?: boolean;
  structural_match_label?: string;
  graph_coverage_note?: string;
  query_structure_source?: string;
  query_position_specified?: boolean;
  query_position_unspecified_match_clusters?: number;
  anchor_overrides_applied?: { component: boolean; fault: boolean; location: boolean };
  manual_anchor_override?: boolean;
};

export type DiagnoseResponse = {
  result: Recommendation;
  meta: {
    rq4_base: string;
    candidate_split: string;
    reranker_role: string;
    rq5_meaning: string;
    technical_correctness_probability: boolean;
    operational_layer?: string;
  };
};

export type InsightsResponse = {
  recurring: RecurringItem[];
  components: FrequencyItem[];
  faults: FrequencyItem[];
  actions: FrequencyItem[];
  outcomes: FrequencyItem[];
  matrix: { components: string[]; faults: string[]; values: number[][] };
  component_options: string[];
  selected_component: string;
  selected_fault: string;
  component_actions: FrequencyItem[];
  reviewed_aliases?: Array<{ source: string; display_as: string }>;
  note: string;
};

export type CaseRecord = {
  ident: string;
  problem: string;
  problem_raw: string;
  action: string;
  action_raw: string;
  action_family: string;
  action_kind: string;
  outcome: string;
  outcome_label: string;
  component: string;
  fault: string;
  locations: string[];
  entities: Entity[];
  relations: Relation[];
  evidence_cluster: string;
  split: string;
  problem_may_be_truncated: boolean;
  action_may_be_truncated: boolean;
};

export type GraphNode = {
  id: string;
  label: string;
  kind: "component" | "fault" | "action";
  count: number;
  focused: boolean;
};

export type GraphEdge = {
  source: string;
  target: string;
  kind: "component_fault" | "fault_action";
  count: number;
};

export type GraphResponse = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  focus_component: string;
  component_options: string[];
  parameters: { top_components: number; top_faults: number; min_edge: number };
  scope?: { label: string; records: number; action_basis: string };
  note: string;
};

export type JobCard = {
  title: string;
  component: string;
  fault: string;
  work_orders: number;
  problem_groups: number;
  dominant_action: string;
  steps: Array<{ text: string; source_idents: string[]; source_may_be_truncated?: boolean }>;
  references: string[];
  outcome_positive: number;
  outcome_negative: number;
  outcome_unknown: number;
  source_idents: string[];
};

export type EvaluationResponse = {
  frozen: {
    rq4: Record<string, any> | null;
    rq5: Record<string, any> | null;
    manual: Record<string, any> | null;
    lock: Record<string, any> | null;
  };
  warning: string;
};

export type WatchlistEntry = {
  id: string;
  addedAt: string;
  query: string;
  recommendation: string;
  actionFamily: string;
  component: string;
  evidenceGrade: string;
  agreement: number | null;
  supportClusters: number;
  anchorCoverage: number;
};

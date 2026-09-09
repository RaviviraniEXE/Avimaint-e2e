import { describe, expect, it } from "vitest";
import { badgeLabel, percent, recommendationToWatchlist, score } from "../utils";
import { DEFAULT_RETRIEVAL_DEPTH } from "../api/client";
import type { Recommendation } from "../api/types";
import { pageKeyFromHash } from "../App";

describe("evidence presentation", () => {
  it("opens the overview for a new or invalid route", () => {
    expect(pageKeyFromHash("")).toBe("overview");
    expect(pageKeyFromHash("#/unknown")).toBe("overview");
    expect(pageKeyFromHash("#/diagnose")).toBe("diagnose");
  });

  it("keeps the frontend on the frozen top-50 retrieval depth", () => {
    expect(DEFAULT_RETRIEVAL_DEPTH).toBe(50);
  });

  it("uses evidence wording rather than safety-confidence wording", () => {
    expect(badgeLabel.strong).toBe("Strong historical evidence");
    expect(badgeLabel.limited).toBe("Limited historical evidence");
    expect(badgeLabel.abstain).toBe("Nearest cases only");
  });

  it("formats missing and finite values safely", () => {
    expect(percent(0.88684, 1)).toBe("88.7%");
    expect(percent(null)).toBe("n/a");
    expect(score(Number.NaN)).toBe("n/a");
  });

  it("preserves evidence metadata in a planning handoff", () => {
    const recommendation = {
      query: "#2 INTAKE LEAKING",
      structured_sentence: "Review the recorded replacement strategy.",
      action_set_summary: "Primary recorded option: Replace the intake gasket. Limited one-cluster alternative: Repair the intake gasket.",
      headline_action: "Replace",
      components: ["INTAKE"],
      badge: "limited",
      historical_agreement_probability: 0.62,
      support_clusters: 1,
      anchor_coverage: 0.75,
    } as Recommendation;
    const item = recommendationToWatchlist(recommendation);
    expect(item.evidenceGrade).toBe("Limited historical evidence");
    expect(item.recommendation).toContain("Limited one-cluster alternative");
    expect(item.supportClusters).toBe(1);
    expect(item.agreement).toBe(0.62);
  });
});

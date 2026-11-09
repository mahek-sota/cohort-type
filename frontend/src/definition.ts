import type { Evidence, Judgments, Preset } from "./api";

export const DEFAULT_THRESHOLD = 6.5;

/**
 * The builder's controls. Unlike Judgments, this keeps inactive settings, so switching from
 * codes to labs and back doesn't lose the code groups or the threshold.
 */
export interface Draft {
  evidence: Evidence;
  includeDiagnosis: boolean;
  includeComplications: boolean;
  includeOtherComplications: boolean;
  includePrediabetes: boolean;
  threshold: number;
}

export function draftFromJudgments(judgments: Judgments): Draft {
  return {
    evidence: judgments.evidence,
    includeDiagnosis: judgments.include_diagnosis ?? false,
    includeComplications: judgments.include_complications ?? false,
    includeOtherComplications: judgments.include_other_complications ?? false,
    includePrediabetes: judgments.include_prediabetes ?? false,
    threshold: judgments.hba1c_threshold ?? DEFAULT_THRESHOLD,
  };
}

/** Returns the judgments to send, or null when the draft isn't a complete definition yet. */
export function judgmentsFromDraft(draft: Draft): Judgments | null {
  if (draft.evidence === "labs") {
    return { evidence: "labs", hba1c_threshold: draft.threshold };
  }
  const codeGroups = {
    include_diagnosis: draft.includeDiagnosis,
    include_complications: draft.includeComplications,
    include_other_complications: draft.includeOtherComplications,
    include_prediabetes: draft.includePrediabetes,
  };
  if (!Object.values(codeGroups).some(Boolean)) {
    return null;
  }
  return draft.evidence === "codes"
    ? { evidence: "codes", ...codeGroups }
    : { evidence: "both", ...codeGroups, hba1c_threshold: draft.threshold };
}

function sameDefinition(a: Judgments | null, b: Judgments | null): boolean {
  return a !== null && b !== null && JSON.stringify(a) === JSON.stringify(b);
}

/** Finds the preset this draft currently matches, so a changed draft stops claiming its name. */
export function matchingPreset(draft: Draft, presets: Preset[]): Preset | undefined {
  const judgments = judgmentsFromDraft(draft);
  return presets.find((preset) =>
    sameDefinition(judgments, judgmentsFromDraft(draftFromJudgments(preset.judgments))),
  );
}

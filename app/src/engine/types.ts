// Core domain types for the eligibility engine.
// See docs/ARCHITECTURE.md §5 (data model) and §6 (algorithms).

export type Benefit =
  | "free"
  | "discount_50"
  | "discount_other"
  | "varies"
  | "none";

/** UI-facing classification tier. */
export type Tier = "free" | "discount" | "verify" | "none";

export type Anchor = "home_institution" | "residence" | "inter_institution";

export interface Exclusion {
  /** Straight-line radius in miles. */
  radius_mi?: number;
  /** Which reference points to measure from. Evaluated with OR. */
  anchors: Anchor[];
  /** If true, the rule applies only when a museum explicitly opts in. */
  discretionary?: boolean;
}

export interface ProgramDef {
  name: string;
  color: string;
  default_benefit: Benefit;
  default_admits: number;
  default_exclusion: Exclusion | null;
}

export type Programs = Record<string, ProgramDef>;

/** A museum's participation in one program. */
export interface MuseumProgramEntry {
  benefit?: Benefit;
  admits?: number;
  /** null/undefined => fall back to the program's default_exclusion. */
  exclusion?: Exclusion | null;
  /** Program-specific tier, e.g. AZA "100_or_50" (in-kind: free between same-tier zoos). */
  tier?: string;
  notes?: string;
  verified?: string;
}

export interface LatLng {
  lat: number;
  lng: number;
}

export interface Museum extends LatLng {
  id: string;
  name: string;
  type?: string;
  programs: Record<string, MuseumProgramEntry>;
}

/** A museum the user is a member of; contributes programs AND a distance anchor. */
export interface HomeInstitution extends LatLng {
  id?: string;
  /** Programs this membership grants. */
  programs: string[];
  /** This institution's own tier per program (see MuseumProgramEntry.tier). */
  tiers?: Record<string, string | undefined>;
}

export interface UserProfile {
  /** Union of programs from home museums and directly-selected associations. */
  heldPrograms: string[];
  /** Empty when the user only picked associations (no specific home museum). */
  homeInstitutions: HomeInstitution[];
  /** Residence, resolved to a centroid. Optional but strongly recommended. */
  zipCentroid?: LatLng;
}

export interface Option {
  program: string;
  benefit: Benefit;
  admits: number;
  color: string;
}

export type Reason = "eligible" | "no_shared_program" | "excluded_by_distance";

export interface Classification {
  tier: Tier;
  reason: Reason;
  /** Applicable (non-excluded) options, color-coded for the UI. */
  options: Option[];
  /** Best option to use, or null when not covered. */
  recommended: Option | null;
}

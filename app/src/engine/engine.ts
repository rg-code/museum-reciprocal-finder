// Pure eligibility engine. No I/O, no framework — just data in, classification out.
// See docs/ARCHITECTURE.md §6.

import type {
  Benefit,
  Classification,
  Exclusion,
  HomeInstitution,
  LatLng,
  Museum,
  MuseumProgramEntry,
  Option,
  Programs,
  Tier,
  UserProfile,
} from "./types.js";

const EARTH_RADIUS_MI = 3958.7613;

/** Great-circle distance in miles ("as the crow flies"). */
export function haversineMiles(a: LatLng, b: LatLng): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_MI * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function tierOf(benefit: Benefit): Tier {
  switch (benefit) {
    case "free":
      return "free";
    case "discount_50":
    case "discount_other":
      return "discount";
    case "varies":
      return "verify";
    default:
      return "none";
  }
}

const TIER_RANK: Record<Tier, number> = { free: 3, discount: 2, verify: 1, none: 0 };

interface ResolvedExclusion {
  excl: Exclusion | null;
  /** True when the museum's own record set an exclusion (vs. inheriting default). */
  optedIn: boolean;
}

function resolveExclusion(
  entry: MuseumProgramEntry,
  defaultExclusion: Exclusion | null,
): ResolvedExclusion {
  if (entry.exclusion) return { excl: entry.exclusion, optedIn: true };
  return { excl: defaultExclusion, optedIn: false };
}

/**
 * True if this program's benefit is blocked at museum M for this user.
 * Exclusion is OR across anchors: the first anchor within the radius blocks it.
 * (Confirmed ASTC behavior — within 90 mi of home institution OR residence.)
 */
export function isExcluded(
  museum: Museum,
  user: UserProfile,
  program: string,
  resolved: ResolvedExclusion,
): boolean {
  const { excl, optedIn } = resolved;
  if (!excl) return false;
  if (excl.discretionary && !optedIn) return false; // optional rule, museum didn't opt in
  const r = excl.radius_mi;
  if (r == null) return false;

  const grantingHomes = (user.homeInstitutions ?? []).filter((h) =>
    h.programs.includes(program),
  );

  for (const anchor of excl.anchors) {
    if (anchor === "home_institution" || anchor === "inter_institution") {
      for (const h of grantingHomes) {
        if (haversineMiles(museum, h) < r) return true;
      }
    }
    if (anchor === "residence" && user.zipCentroid) {
      if (haversineMiles(museum, user.zipCentroid) < r) return true;
    }
  }
  return false;
}

/** Every program the user could actually use at M, after distance exclusions. */
/**
 * AZA reciprocity is in-kind: a "100% OR 50%" zoo gives 100% to members of
 * another "100% OR 50%" zoo and 50% to everyone else (stored as discount_50).
 */
export const IN_KIND_TIER = "100_or_50";

export function applicableOptions(
  museum: Museum,
  user: UserProfile,
  programs: Programs,
): Option[] {
  const held = new Set(user.heldPrograms);
  const options: Option[] = [];
  for (const [program, entry] of Object.entries(museum.programs)) {
    if (!held.has(program)) continue;
    const def = programs[program];
    if (!def) continue;
    let benefit: Benefit = entry.benefit ?? def.default_benefit;
    if (entry.tier === IN_KIND_TIER &&
        user.homeInstitutions.some((h) => h.tiers?.[program] === IN_KIND_TIER)) {
      benefit = "free";
    }
    const admits = entry.admits ?? def.default_admits;
    const resolved = resolveExclusion(entry, def.default_exclusion);
    if (isExcluded(museum, user, program, resolved)) continue;
    options.push({ program, benefit, admits, color: def.color });
  }
  return options;
}

/**
 * Pick the option to recommend when a museum is in several of the user's networks:
 * best tier first, then most people admitted, then stable program order.
 */
export function recommendedOption(options: Option[]): Option | null {
  if (options.length === 0) return null;
  return [...options].sort((a, b) => {
    const t = TIER_RANK[tierOf(b.benefit)] - TIER_RANK[tierOf(a.benefit)];
    if (t !== 0) return t;
    if (b.admits !== a.admits) return b.admits - a.admits;
    return a.program.localeCompare(b.program);
  })[0];
}

/** Classify one museum for one user. */
export function classifyMuseum(
  museum: Museum,
  user: UserProfile,
  programs: Programs,
): Classification {
  const held = new Set(user.heldPrograms);
  const shared = Object.keys(museum.programs).filter((p) => held.has(p));
  if (shared.length === 0) {
    return { tier: "none", reason: "no_shared_program", options: [], recommended: null };
  }
  const options = applicableOptions(museum, user, programs);
  if (options.length === 0) {
    return { tier: "none", reason: "excluded_by_distance", options: [], recommended: null };
  }
  const recommended = recommendedOption(options)!;
  return { tier: tierOf(recommended.benefit), reason: "eligible", options, recommended };
}

/** Convenience: build the held-programs set from home museums + selected associations. */
export function heldProgramsFrom(
  homeInstitutions: HomeInstitution[],
  associations: string[] = [],
): string[] {
  const set = new Set<string>(associations);
  for (const h of homeInstitutions) for (const p of h.programs) set.add(p);
  return [...set];
}

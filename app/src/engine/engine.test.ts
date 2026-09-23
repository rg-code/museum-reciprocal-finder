// Unit tests for the eligibility engine. Run: npm test  (node --test via tsx)
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  exclusionReason,
  haversineMiles,
  tierOf,
  isExcluded,
  applicableOptions,
  recommendedOption,
  classifyMuseum,
  heldProgramsFrom,
} from "./engine.js";
import type { Museum, Programs, UserProfile } from "./types.js";

// Minimal program table mirroring data/programs.json defaults.
const PROGRAMS: Programs = {
  ASTC: {
    name: "ASTC", color: "#1f77b4", default_benefit: "free", default_admits: 2,
    default_exclusion: { radius_mi: 90, anchors: ["home_institution", "residence"], discretionary: false },
  },
  NARM: {
    name: "NARM", color: "#9467bd", default_benefit: "free", default_admits: 2,
    default_exclusion: { radius_mi: 15, anchors: ["home_institution"], discretionary: true },
  },
  ROAM: {
    name: "ROAM", color: "#2ca02c", default_benefit: "free", default_admits: 2,
    default_exclusion: { radius_mi: 25, anchors: ["inter_institution"], discretionary: false },
  },
  ACM: {
    name: "ACM", color: "#d62728", default_benefit: "discount_50", default_admits: 6,
    default_exclusion: null,
  },
  TIMETRAVELERS: {
    name: "Time Travelers", color: "#e377c2", default_benefit: "varies", default_admits: 2,
    default_exclusion: null,
  },
};

// Kansas City area coordinates.
const KC = { lat: 39.0997, lng: -94.5786 };
const NYC = { lat: 40.7128, lng: -74.006 };

function museum(id: string, at: { lat: number; lng: number }, programs: Museum["programs"]): Museum {
  return { id, name: id, lat: at.lat, lng: at.lng, programs };
}

test("haversine: KC to NYC is ~1100 miles", () => {
  const d = haversineMiles(KC, NYC);
  assert.ok(d > 1050 && d < 1150, `got ${d}`);
});

test("tierOf maps benefits to tiers", () => {
  assert.equal(tierOf("free"), "free");
  assert.equal(tierOf("discount_50"), "discount");
  assert.equal(tierOf("varies"), "verify");
  assert.equal(tierOf("none"), "none");
});

test("ASTC exclusion is OR: within 90mi of residence blocks even if home institution is far", () => {
  const m = museum("near-home", { lat: 39.2, lng: -94.6 }, { ASTC: {} }); // ~7 mi from KC
  const user: UserProfile = {
    heldPrograms: ["ASTC"],
    homeInstitutions: [{ lat: NYC.lat, lng: NYC.lng, programs: ["ASTC"] }], // home institution far away
    zipCentroid: KC, // but residence is near the museum
  };
  const resolved = { excl: PROGRAMS.ASTC.default_exclusion, optedIn: false };
  assert.equal(isExcluded(m, user, "ASTC", resolved), true);
});

test("ASTC: eligible only when BOTH residence and home institution are >90mi away", () => {
  const m = museum("far", NYC, { ASTC: {} });
  const user: UserProfile = {
    heldPrograms: ["ASTC"],
    homeInstitutions: [{ lat: KC.lat, lng: KC.lng, programs: ["ASTC"] }],
    zipCentroid: KC,
  };
  const c = classifyMuseum(m, user, PROGRAMS);
  assert.equal(c.tier, "free");
  assert.equal(c.reason, "eligible");
});

test("discretionary rule does not apply when the museum didn't opt in", () => {
  // NARM default exclusion is discretionary; museum sets no explicit exclusion.
  const m = museum("narm-near", { lat: 39.11, lng: -94.58 }, { NARM: {} }); // ~1 mi from KC residence
  const user: UserProfile = { heldPrograms: ["NARM"], homeInstitutions: [], zipCentroid: KC };
  const c = classifyMuseum(m, user, PROGRAMS);
  assert.equal(c.tier, "free", "not excluded because NARM rule is discretionary + not opted in");
});

test("discretionary rule DOES apply when the museum opts in", () => {
  const m = museum("narm-optin", { lat: 39.11, lng: -94.58 }, {
    NARM: { exclusion: { radius_mi: 15, anchors: ["residence"] } },
  });
  const user: UserProfile = { heldPrograms: ["NARM"], homeInstitutions: [], zipCentroid: KC };
  const c = classifyMuseum(m, user, PROGRAMS);
  assert.equal(c.tier, "none");
  assert.equal(c.reason, "excluded_by_distance");
});

test("overlap: free NARM beats 50% ACM, but both chips are surfaced", () => {
  const m = museum("childrens", NYC, { NARM: {}, ACM: {} });
  const user: UserProfile = { heldPrograms: ["NARM", "ACM"], homeInstitutions: [], zipCentroid: KC };
  const c = classifyMuseum(m, user, PROGRAMS);
  assert.equal(c.tier, "free");
  assert.equal(c.recommended?.program, "NARM");
  assert.equal(c.options.length, 2, "both associations remain visible");
});

test("overlap tie-break by admits when both are free", () => {
  const opts = [
    { program: "NARM", benefit: "free" as const, admits: 2, color: "#9467bd" },
    { program: "ROAM", benefit: "free" as const, admits: 4, color: "#2ca02c" },
  ];
  assert.equal(recommendedOption(opts)?.program, "ROAM");
});

test("no shared program => not covered (outside your networks)", () => {
  const m = museum("aza-zoo", NYC, { AZA: {} });
  const user: UserProfile = { heldPrograms: ["NARM"], homeInstitutions: [], zipCentroid: KC };
  const c = classifyMuseum(m, user, PROGRAMS);
  assert.equal(c.tier, "none");
  assert.equal(c.reason, "no_shared_program");
});

test("varies program (Time Travelers) => verify tier", () => {
  const m = museum("history", NYC, { TIMETRAVELERS: {} });
  const user: UserProfile = { heldPrograms: ["TIMETRAVELERS"], homeInstitutions: [], zipCentroid: KC };
  const c = classifyMuseum(m, user, PROGRAMS);
  assert.equal(c.tier, "verify");
});

test("applicableOptions carries per-program color", () => {
  const m = museum("multi", NYC, { NARM: {}, ACM: {} });
  const user: UserProfile = { heldPrograms: ["NARM", "ACM"], homeInstitutions: [], zipCentroid: KC };
  const opts = applicableOptions(m, user, PROGRAMS);
  const narm = opts.find((o) => o.program === "NARM");
  assert.equal(narm?.color, "#9467bd");
});

test("heldProgramsFrom unions home museums and associations", () => {
  const held = heldProgramsFrom(
    [{ lat: 0, lng: 0, programs: ["ASTC", "NARM"] }],
    ["ACM"],
  );
  assert.deepEqual([...held].sort(), ["ACM", "ASTC", "NARM"]);
});

test("AZA in-kind: a 100%-OR-50% zoo is free only for members of another 100%-OR-50% zoo", () => {
  const programs: Programs = {
    AZA: { name: "AZA", color: "#ff7f0e", default_benefit: "discount_50", default_admits: 2,
      default_exclusion: { anchors: ["inter_institution"], discretionary: true } },
  };
  const far = { lat: 30, lng: -100 };
  const zoo = museum("zoo-boise", KC, { AZA: { benefit: "discount_50", tier: "100_or_50" } });
  const plain = museum("birmingham-zoo", KC, { AZA: { benefit: "discount_50" } });
  const blueHome: UserProfile = { heldPrograms: ["AZA"], zipCentroid: NYC,
    homeInstitutions: [{ ...far, programs: ["AZA"], tiers: { AZA: "100_or_50" } }] };
  const redHome: UserProfile = { heldPrograms: ["AZA"], zipCentroid: NYC,
    homeInstitutions: [{ ...far, programs: ["AZA"], tiers: {} }] };
  assert.equal(applicableOptions(zoo, blueHome, programs)[0].benefit, "free");
  assert.equal(applicableOptions(zoo, redHome, programs)[0].benefit, "discount_50");
  assert.equal(applicableOptions(plain, blueHome, programs)[0].benefit, "discount_50");
});

test("AZA in-kind via the association checkbox: blue tier gets free at blue zoos, red stays 50%", () => {
  const programs: Programs = {
    AZA: { name: "AZA", color: "#ff7f0e", default_benefit: "discount_50", default_admits: 2,
      default_exclusion: { anchors: ["inter_institution"], discretionary: true } },
  };
  const blueZoo = museum("zoo-boise", KC, { AZA: { benefit: "discount_50", tier: "100_or_50" } });
  const redZoo = museum("birmingham-zoo", KC, { AZA: { benefit: "discount_50" } });
  const publicZoo = museum("lincoln-park-zoo", KC, { AZA: { benefit: "free", tier: "free_public" } });
  const blue: UserProfile = { heldPrograms: ["AZA"], homeInstitutions: [], zipCentroid: NYC, associationTiers: { AZA: "100_or_50" } };
  const red: UserProfile = { heldPrograms: ["AZA"], homeInstitutions: [], zipCentroid: NYC, associationTiers: { AZA: "50" } };
  assert.equal(applicableOptions(blueZoo, blue, programs)[0].benefit, "free");
  assert.equal(applicableOptions(redZoo, blue, programs)[0].benefit, "discount_50");
  assert.equal(applicableOptions(blueZoo, red, programs)[0].benefit, "discount_50");
  assert.equal(applicableOptions(publicZoo, red, programs)[0].benefit, "free");
});

test("classifyMuseum says why: blocked programs with their rule, and the networks you'd need", () => {
  const near = museum("near-science", KC, { ASTC: {}, NARM: {} });
  const user: UserProfile = { heldPrograms: ["ASTC"], homeInstitutions: [], zipCentroid: KC };
  const c = classifyMuseum(near, user, PROGRAMS);
  assert.equal(c.reason, "excluded_by_distance");
  assert.deepEqual(c.blocked, [{ program: "ASTC", color: PROGRAMS.ASTC.color, anchor: "residence", radius: 90 }]);
  assert.deepEqual(c.others, ["NARM"]);
  const acmOnly = museum("kids", KC, { ACM: {} });
  const d = classifyMuseum(acmOnly, user, PROGRAMS);
  assert.equal(d.reason, "no_shared_program");
  assert.deepEqual(d.others, ["ACM"]);
  const home = { id: "home-museum", lat: KC.lat, lng: KC.lng, programs: ["ASTC"] };
  const r = exclusionReason(near, { ...user, zipCentroid: NYC, homeInstitutions: [home] }, "ASTC",
    { excl: PROGRAMS.ASTC.default_exclusion, optedIn: false });
  assert.deepEqual(r, { anchor: "home", radius: 90, homeId: "home-museum" });
});

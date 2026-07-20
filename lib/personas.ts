import type { Persona } from "./types";

/** Product personas offered by the authenticated workspace UI. */
export const PERSONAS: Persona[] = [
  { id: "support", title: "Support Agent", focus: "Resolve incidents with cited answers" },
  { id: "sales", title: "Sales Engineer", focus: "Answer technical evaluations with evidence" },
  { id: "compliance", title: "Compliance Officer", focus: "Review obligations and control gaps" },
  { id: "ops", title: "Operations Manager", focus: "Assess reliability and operating risks" },
  { id: "architect", title: "Solutions Architect", focus: "Validate designs against documented constraints" },
  { id: "newhire", title: "New Hire", focus: "Build a role-specific onboarding plan" },
];

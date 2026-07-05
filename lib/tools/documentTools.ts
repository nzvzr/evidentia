import type { DocumentSection, PersonaBrief } from "@/lib/types";

const STOP = new Set([
  "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is", "are",
  "with", "by", "be", "as", "at", "must", "should", "this", "that",
]);

function tokens(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((t) => t.length > 2 && !STOP.has(t));
}

function scoreOverlap(haystack: string, needles: string[]): number {
  const hay = new Set(tokens(haystack));
  let score = 0;
  for (const n of needles) if (hay.has(n)) score += 1;
  return score;
}

/** Keyword-rank sections against a free-text query. */
export function searchDocumentSections({
  sections,
  query,
  limit = 6,
}: {
  sections: DocumentSection[];
  query: string;
  limit?: number;
}): DocumentSection[] {
  const needles = tokens(query);
  if (needles.length === 0) return sections.slice(0, limit);
  return [...sections]
    .map((s) => ({ s, score: scoreOverlap(`${s.sectionTitle} ${s.excerpt}`, needles) }))
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((x) => x.s);
}

/** Rank sections by relevance to a persona brief and market. */
export function rankSectionsForPersona({
  sections,
  personaBrief,
  market,
}: {
  sections: DocumentSection[];
  personaBrief: PersonaBrief;
  market: string;
}): DocumentSection[] {
  const needles = tokens(
    [
      ...personaBrief.relevantTopics,
      ...personaBrief.priorities,
      ...personaBrief.riskFocus,
      market,
    ].join(" "),
  );
  return [...sections]
    .map((s) => ({ s, score: scoreOverlap(`${s.sectionTitle} ${s.excerpt} ${s.category}`, needles) }))
    .sort((a, b) => b.score - a.score)
    .map((x) => x.s);
}

/** Return only the sections matching the given citation ids (order preserved). */
export function getSectionsByCitationIds({
  sections,
  citationIds,
}: {
  sections: DocumentSection[];
  citationIds: string[];
}): DocumentSection[] {
  const wanted = new Set(citationIds);
  return sections.filter((s) => wanted.has(s.citationId));
}

/** Build a compact, token-bounded context block for an LLM prompt. */
export function summarizeSectionsForPrompt({
  sections,
  maxChars = 2400,
}: {
  sections: DocumentSection[];
  maxChars?: number;
}): string {
  const lines: string[] = [];
  let used = 0;
  for (const s of sections) {
    const line = `[${s.citationId}] ${s.source} — ${s.sectionTitle}: ${s.excerpt}`;
    if (used + line.length > maxChars) break;
    lines.push(line);
    used += line.length + 1;
  }
  return lines.join("\n");
}

function matches(section: DocumentSection, keywords: string[]): boolean {
  const hay = `${section.sectionTitle} ${section.excerpt}`.toLowerCase();
  return keywords.some((k) => hay.includes(k));
}

/** Sections that evidence data-residency / sovereignty concerns. */
export function findResidencyRisks({
  sections,
  market,
}: {
  sections: DocumentSection[];
  market?: string;
}): DocumentSection[] {
  const keywords = ["residency", "region", "in-region", "sovereign", "us-east-1", "metadata", "processed"];
  const found = sections.filter((s) => matches(s, keywords));
  // Market context is advisory; high-compliance markets amplify relevance upstream.
  void market;
  return found;
}

/** Sections that evidence SLA / availability / credit concerns. */
export function findSlaRisks({ sections }: { sections: DocumentSection[] }): DocumentSection[] {
  return sections.filter((s) => matches(s, ["sla", "availability", "uptime", "credit", "outage", "multi-region"]));
}

/** Sections that evidence API rate-limit / integration concerns. */
export function findApiRisks({ sections }: { sections: DocumentSection[] }): DocumentSection[] {
  return sections.filter((s) => matches(s, ["api", "rate limit", "requests per minute", "token", "webhook", "backoff"]));
}

/** Sections that evidence incident escalation / on-call concerns. */
export function findIncidentEscalationRisks({ sections }: { sections: DocumentSection[] }): DocumentSection[] {
  return sections.filter((s) =>
    matches(s, ["incident", "severity", "escalat", "on-call", "pagertree", "deprecated", "page"]),
  );
}

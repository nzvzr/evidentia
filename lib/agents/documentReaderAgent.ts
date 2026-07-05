import { DEMO_DOCUMENTS, DEFAULT_DOCUMENT_IDS, getDocumentMeta } from "@/data/demoDocuments";
import { DOCUMENT_CONTENT } from "@/data/documentContent";
import type { DocumentMeta, DocumentSection } from "@/lib/types";

export interface DocumentReaderResult {
  documents: DocumentMeta[];
  sections: DocumentSection[];
}

/** Split a markdown string into `## ` sections with a leading paragraph excerpt. */
function parseSections(markdown: string): { title: string; excerpt: string }[] {
  const lines = markdown.split(/\r?\n/);
  const sections: { title: string; excerpt: string }[] = [];
  let current: { title: string; body: string[] } | null = null;

  for (const line of lines) {
    const heading = line.match(/^##\s+(.*)$/);
    if (heading) {
      if (current) sections.push({ title: current.title, excerpt: current.body.join(" ").trim() });
      current = { title: heading[1].trim(), body: [] };
    } else if (current && line.trim() && !line.startsWith("#")) {
      current.body.push(line.trim());
    }
  }
  if (current) sections.push({ title: current.title, excerpt: current.body.join(" ").trim() });
  return sections;
}

/**
 * Document Reader / Ingest Agent.
 * Loads matching demo documents, reads their markdown content, splits it into
 * sections, and attaches a source-traceable citation id to each section.
 */
export function documentReaderAgent(selectedDocumentIds: string[]): DocumentReaderResult {
  const ids =
    selectedDocumentIds && selectedDocumentIds.length > 0
      ? selectedDocumentIds
      : DEFAULT_DOCUMENT_IDS;

  const documents: DocumentMeta[] = [];
  const sections: DocumentSection[] = [];

  for (const id of ids) {
    const meta = getDocumentMeta(id);
    if (!meta) continue;
    documents.push(meta);
    const content = DOCUMENT_CONTENT[id] ?? "";
    const parsed = parseSections(content);
    parsed.forEach((s, i) => {
      const citationId = meta.citationIds[i] ?? `${meta.citationPrefix}-${i + 1}`;
      sections.push({
        documentId: meta.id,
        source: meta.title,
        sectionTitle: s.title,
        excerpt: s.excerpt,
        category: meta.category,
        citationId,
      });
    });
  }

  // Guarantee at least the default corpus if nothing matched.
  if (documents.length === 0) {
    return documentReaderAgent(DEFAULT_DOCUMENT_IDS);
  }

  return { documents, sections };
}

export { DEMO_DOCUMENTS };

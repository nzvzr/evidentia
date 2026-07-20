import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("tenant-only runtime boundary", () => {
  it("does not ship the anonymous workflow route or local report pipeline", () => {
    const removed = [
      "app/api/demo/generate-workflow/route.ts",
      "lib/demoDocs.ts",
      "lib/demoReport.ts",
      "data/demoDocuments.ts",
      "data/demoReports.ts",
      "lib/agents/orchestrator.ts",
    ];

    for (const relativePath of removed) {
      expect(existsSync(join(process.cwd(), relativePath)), relativePath).toBe(false);
    }
  });
});

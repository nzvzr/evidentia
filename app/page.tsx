"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import AuthModal from "@/components/AuthModal";
import { useSession } from "@/components/SessionProvider";
import Logo from "@/components/Logo";

const NAV_LINKS = [
  { label: "Product", href: "#product" },
  { label: "Security", href: "#security" },
  { label: "Docs", href: "#docs" },
  { label: "Pricing", href: "#pricing" },
];

const FEATURES = [
  {
    n: "01",
    title: "Persona-aware synthesis",
    body: "Models the reader's role, then reshapes the same corpus into their operating priorities.",
  },
  {
    n: "02",
    title: "Traceable citations",
    body: "Every claim links to a source span : page, section, and verbatim snippet.",
  },
  {
    n: "03",
    title: "Risk detection",
    body: "Surfaces compliance gaps, stale references, and undefined terms before they ship.",
  },
  {
    n: "04",
    title: "Exportable playbooks",
    body: "One click turns the brief into a formatted, cited PDF for the field.",
  },
];

const SECURITY_CARDS = [
  {
    n: "01",
    title: "Every claim cited",
    body: "Claims carry a citation ID resolving to a source passage.",
  },
  {
    n: "02",
    title: "Auditable trail",
    body: "A source appendix accompanies every exported playbook.",
  },
  {
    n: "03",
    title: "No black box",
    body: "Reasoning is grounded in your documents — never invented.",
  },
];

const DOC_TYPES = [
  { name: "Policies and standards", meta: "MARKDOWN OR TEXT" },
  { name: "Operating procedures", meta: "MARKDOWN OR TEXT" },
  { name: "Technical reference notes", meta: "MARKDOWN OR TEXT" },
  { name: "Enablement guides", meta: "MARKDOWN OR TEXT" },
];

const PRICING = [
  {
    name: "Starter",
    blurb: "For individuals exploring workflows",
    price: "$0",
    unit: "/ month",
    features: ["1 workspace", "3 documents per run", "Cited playbook export", "Community support"],
    cta: "Get started",
    featured: false,
  },
  {
    name: "Team",
    blurb: "For go-to-market and enablement teams",
    price: "$49",
    unit: "/ seat / month",
    features: ["Unlimited workspaces", "Full document corpus", "All personas & markets", "Shared playbook library"],
    cta: "Start free trial",
    featured: true,
  },
  {
    name: "Enterprise",
    blurb: "For regulated, large-scale orgs",
    price: "Custom",
    unit: "",
    features: ["SSO & SCIM", "Private document connectors", "Audit logs & retention", "Dedicated support"],
    cta: "Contact sales",
    featured: false,
  },
];

export default function LandingPage() {
  const router = useRouter();
  const { isAuthenticated } = useSession();
  const [authOpen, setAuthOpen] = useState(false);
  // Signed in → straight to the workspace. Otherwise register first: the
  // workspace is a protected route and would bounce to /login anyway.
  const goCreate = () => router.push(isAuthenticated ? "/workspace" : "/register");

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0b", color: "#f5f5f3", ...gridBg }}>
      {/* nav */}
      <nav style={{ ...container, padding: "22px 32px", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid rgba(255,255,255,.09)" }}>
        <Logo size={30} showWordmark wordmarkColor="#f5f5f3" />
        <div style={{ display: "flex", alignItems: "center", gap: 30, fontSize: 13.5 }} className="hidden md:flex">
          {NAV_LINKS.map((l) => (
            <a key={l.href} href={l.href} style={{ color: "rgba(245,245,243,.62)" }} className="ev-navlink">
              {l.label}
            </a>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <button onClick={() => setAuthOpen(true)} style={{ fontFamily: "inherit", fontSize: 13.5, color: "rgba(245,245,243,.62)", background: "transparent", border: "none", cursor: "pointer" }}>
            Sign in
          </button>
          <button onClick={goCreate} style={{ fontFamily: "inherit", fontSize: 13.5, fontWeight: 600, color: "#0a0a0b", background: "#fff", border: "none", padding: "9px 16px", borderRadius: 7, cursor: "pointer" }}>
            Launch workspace
          </button>
        </div>
      </nav>

      {/* hero */}
      <header style={{ ...container, padding: "88px 32px 44px" }}>
        <div style={{ fontFamily: mono, fontSize: 12, letterSpacing: ".22em", color: "var(--accent)", textTransform: "uppercase", marginBottom: 28 }}>
          Persona-Aware Documentation Agent
        </div>
        <h1 style={{ fontSize: "clamp(40px,7vw,66px)", lineHeight: 1.02, letterSpacing: "-.03em", fontWeight: 700, margin: 0, maxWidth: "16ch" }}>
          Turn static documentation into role-specific workflows.
        </h1>
        <p style={{ fontSize: 19, lineHeight: 1.55, color: "rgba(245,245,243,.6)", maxWidth: "56ch", margin: "28px 0 0" }}>
          Evidentia deploys a multi-agent pipeline over your enterprise docs, modeling the reader&apos;s role, retrieving evidence, flagging risk, and composing a cited, exportable playbook. Not a chatbot. An operating brief.
        </p>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 40, flexWrap: "wrap" }}>
          <button onClick={goCreate} style={{ fontFamily: "inherit", fontSize: 15, fontWeight: 600, color: "#0a0a0b", background: "#fff", border: "none", padding: "14px 24px", borderRadius: 9, cursor: "pointer" }}>
            Create a workspace →
          </button>
          <button onClick={goCreate} style={{ fontFamily: "inherit", fontSize: 15, fontWeight: 500, color: "#f5f5f3", background: "transparent", border: "1px solid rgba(255,255,255,.22)", padding: "14px 22px", borderRadius: 9, cursor: "pointer" }}>
            Watch the workflow
          </button>
        </div>
      </header>

      {/* product preview */}
      <section style={{ ...container, margin: "36px auto 0", padding: "0 32px" }}>
        <div style={{ border: "1px solid rgba(255,255,255,.1)", borderRadius: "14px 14px 0 0", background: "#0e0e10", overflow: "hidden", boxShadow: "0 -1px 60px rgba(47,86,224,.12)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "13px 16px", borderBottom: "1px solid rgba(255,255,255,.08)" }}>
            {[0, 1, 2].map((i) => (
              <span key={i} style={{ width: 9, height: 9, borderRadius: "50%", background: "rgba(255,255,255,.2)" }} />
            ))}
            <span style={{ fontFamily: mono, fontSize: 11, color: "rgba(245,245,243,.4)", marginLeft: 10 }}>
              evidentia — solutions architect · emea
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 1, background: "rgba(255,255,255,.08)", borderBottom: "1px solid rgba(255,255,255,.08)" }}>
            {[
              { k: "PERSONA", v: "Role-specific", accent: false },
              { k: "MARKET", v: "Localized", accent: false },
              { k: "OUTPUT", v: "Playbook", accent: false },
              { k: "EVIDENCE", v: "Cited", accent: true },
            ].map((m) => (
              <div key={m.k} style={{ padding: "18px 20px", background: "#0e0e10" }}>
                <div style={{ fontFamily: mono, fontSize: 10.5, color: "rgba(245,245,243,.42)", letterSpacing: ".08em" }}>{m.k}</div>
                <div style={{ fontSize: 28, fontWeight: 700, marginTop: 8, color: m.accent ? "var(--accent)" : "#fff" }}>{m.v}</div>
              </div>
            ))}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 1, background: "rgba(255,255,255,.08)" }}>
            <div style={{ padding: "22px 24px", background: "#0e0e10" }}>
              <div style={{ fontFamily: mono, fontSize: 10.5, color: "rgba(245,245,243,.42)", letterSpacing: ".08em", marginBottom: 16 }}>PLAYBOOK CONTENTS</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
                {[
                  "Configured persona context",
                  "Evidence-backed workflow",
                  "Frozen source appendix",
                ].map((name) => (
                  <div key={name} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--accent)" }} />
                    <span style={{ fontSize: 13, color: "rgba(245,245,243,.85)" }}>{name}</span>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ padding: "22px 24px", background: "#0e0e10" }}>
              <div style={{ fontFamily: mono, fontSize: 10.5, color: "rgba(245,245,243,.42)", letterSpacing: ".08em", marginBottom: 16 }}>PROVENANCE</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
                {[
                  "Document version",
                  "Section path",
                  "Evidence excerpt",
                ].map((label) => (
                  <div key={label}>
                    <div style={{ fontSize: 11, color: "rgba(245,245,243,.6)" }}>{label}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* features */}
      <section style={{ ...container, margin: "96px auto 0", padding: "0 32px 96px" }}>
        <div style={gridCards(4)}>
          {FEATURES.map((f) => (
            <div key={f.n} style={{ padding: "30px 26px", background: "#0a0a0b" }}>
              <div style={{ fontFamily: mono, fontSize: 11, color: "var(--accent)", marginBottom: 14 }}>{f.n}</div>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 9 }}>{f.title}</div>
              <div style={{ fontSize: 13.5, lineHeight: 1.55, color: "rgba(245,245,243,.55)" }}>{f.body}</div>
            </div>
          ))}
        </div>
      </section>

      {/* PRODUCT */}
      <section id="product" style={{ scrollMarginTop: 12, borderTop: "1px solid rgba(255,255,255,.09)" }}>
        <div style={{ ...container, padding: "84px 32px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 64, alignItems: "center" }} className="ev-two-col">
          <div>
            <div style={eyebrow}>Product</div>
            <h2 style={h2}>Persona-aware documentation workflows</h2>
            <p style={{ ...bodyText, maxWidth: "46ch" }}>
              Evidentia reads your static enterprise documentation and reshapes it around a specific role and market — turning reference material into a sequenced, evidence-backed playbook the reader can act on immediately.
            </p>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <FlowCard label="INPUT" title="Static enterprise documentation" />
            <div style={{ textAlign: "center", color: "rgba(245,245,243,.3)", fontSize: 15 }}>↓</div>
            <FlowCard label="EVIDENTIA · 7 AGENTS" title="Model role + market, retrieve evidence" highlight />
            <div style={{ textAlign: "center", color: "rgba(245,245,243,.3)", fontSize: 15 }}>↓</div>
            <FlowCard label="OUTPUT" title="Role-specific, cited playbook" />
          </div>
        </div>
      </section>

      {/* SECURITY */}
      <section id="security" style={{ scrollMarginTop: 12, borderTop: "1px solid rgba(255,255,255,.09)" }}>
        <div style={{ ...container, padding: "84px 32px" }}>
          <div style={eyebrow}>Security</div>
          <h2 style={{ ...h2, maxWidth: "20ch" }}>Citation-backed, auditable outputs</h2>
          <p style={{ ...bodyText, maxWidth: "60ch" }}>
            No black-box recommendations. Every important claim in a playbook links to the exact source span — document, section, and verbatim excerpt — so any output can be traced, reviewed, and defended in a security or compliance review.
          </p>
          <div style={{ ...gridCards(3), marginTop: 40 }}>
            {SECURITY_CARDS.map((c) => (
              <div key={c.n} style={{ padding: "28px 26px", background: "#0a0a0b" }}>
                <div style={{ fontFamily: mono, fontSize: 11, color: "var(--accent)", marginBottom: 12 }}>{c.n}</div>
                <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>{c.title}</div>
                <div style={{ fontSize: 13.5, lineHeight: 1.55, color: "rgba(245,245,243,.55)" }}>{c.body}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* DOCS */}
      <section id="docs" style={{ scrollMarginTop: 12, borderTop: "1px solid rgba(255,255,255,.09)" }}>
        <div style={{ ...container, padding: "84px 32px" }}>
          <div style={eyebrow}>Docs</div>
          <h2 style={h2}>Supported documentation sources</h2>
          <p style={{ ...bodyText, maxWidth: "56ch" }}>
            Upload your organization&apos;s Markdown and plain-text documentation. Evidentia finalizes stable citation identities before a document can be used for generation.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginTop: 36 }} className="ev-doc-grid">
            {DOC_TYPES.map((d) => (
              <div key={d.name} style={{ border: "1px solid rgba(255,255,255,.1)", borderRadius: 10, padding: "18px 18px", background: "#0e0e10" }}>
                <div style={{ fontSize: 14, fontWeight: 600 }}>{d.name}</div>
                <div style={{ fontFamily: mono, fontSize: 10.5, color: "rgba(245,245,243,.4)", marginTop: 8 }}>{d.meta}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* PRICING */}
      <section id="pricing" style={{ scrollMarginTop: 12, borderTop: "1px solid rgba(255,255,255,.09)" }}>
        <div style={{ ...container, padding: "84px 32px 96px" }}>
          <div style={eyebrow}>Pricing</div>
          <h2 style={{ ...h2, margin: "20px 0 44px" }}>Simple, scalable pricing</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16 }} className="ev-pricing-grid">
            {PRICING.map((p) => (
              <div
                key={p.name}
                style={{
                  border: p.featured ? "1px solid #fff" : "1px solid rgba(255,255,255,.12)",
                  borderRadius: 14,
                  padding: "30px 28px",
                  background: p.featured ? "#fff" : "#0e0e10",
                  color: p.featured ? "#0a0a0b" : "#f5f5f3",
                  display: "flex",
                  flexDirection: "column",
                  position: "relative",
                }}
              >
                {p.featured && (
                  <div style={{ position: "absolute", top: -11, left: 28, fontFamily: mono, fontSize: 10, fontWeight: 600, letterSpacing: ".08em", color: "#fff", background: "var(--accent)", padding: "4px 10px", borderRadius: 6 }}>
                    MOST POPULAR
                  </div>
                )}
                <div style={{ fontSize: 15, fontWeight: 600 }}>{p.name}</div>
                <div style={{ fontSize: 12.5, color: p.featured ? "#6b6b70" : "rgba(245,245,243,.5)", marginTop: 6 }}>{p.blurb}</div>
                <div style={{ margin: "22px 0 4px", display: "flex", alignItems: "baseline", gap: 6 }}>
                  <span style={{ fontSize: 38, fontWeight: 700, letterSpacing: "-.02em" }}>{p.price}</span>
                  {p.unit && <span style={{ fontSize: 13, color: p.featured ? "#6b6b70" : "rgba(245,245,243,.5)" }}>{p.unit}</span>}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 11, margin: "24px 0 28px", fontSize: 13.5, color: p.featured ? "#38383c" : "rgba(245,245,243,.7)" }}>
                  {p.features.map((f) => (
                    <div key={f}>{f}</div>
                  ))}
                </div>
                <button
                  onClick={() => setAuthOpen(true)}
                  style={{
                    marginTop: "auto",
                    fontFamily: "inherit",
                    fontSize: 13.5,
                    fontWeight: 600,
                    color: p.featured ? "#fff" : "#f5f5f3",
                    background: p.featured ? "#0a0a0b" : "transparent",
                    border: p.featured ? "none" : "1px solid rgba(255,255,255,.22)",
                    padding: 12,
                    borderRadius: 9,
                    cursor: "pointer",
                  }}
                >
                  {p.cta}
                </button>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* footer */}
      <footer style={{ borderTop: "1px solid rgba(255,255,255,.09)" }}>
        <div style={{ ...container, padding: "26px 32px", display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", fontFamily: mono, fontSize: 11.5, color: "rgba(245,245,243,.4)" }}>
          <span>EVIDENTIA — DOCUMENTATION INTELLIGENCE</span>
          <span>SOC 2 · ISO 27001 · GDPR</span>
        </div>
      </footer>

      <AuthModal open={authOpen} onClose={() => setAuthOpen(false)} onSuccess={goCreate} />

      <style jsx global>{`
        .ev-navlink:hover {
          color: #fff;
        }
        @media (max-width: 860px) {
          .ev-two-col {
            grid-template-columns: 1fr !important;
            gap: 32px !important;
          }
          .ev-doc-grid {
            grid-template-columns: repeat(2, 1fr) !important;
          }
          .ev-pricing-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
}

function FlowCard({ label, title, highlight }: { label: string; title: string; highlight?: boolean }) {
  return (
    <div
      style={{
        border: highlight ? "1px solid var(--accent)" : "1px solid rgba(255,255,255,.1)",
        borderRadius: 11,
        padding: "20px 22px",
        background: highlight ? "rgba(47,86,224,.1)" : "#0e0e10",
      }}
    >
      <div style={{ fontFamily: mono, fontSize: 10, letterSpacing: ".1em", color: highlight ? "var(--accent)" : "rgba(245,245,243,.4)" }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 600, marginTop: 7 }}>{title}</div>
    </div>
  );
}

const mono = "var(--font-plex-mono), monospace";

const container: React.CSSProperties = {
  maxWidth: 1200,
  margin: "0 auto",
};

const gridBg: React.CSSProperties = {
  backgroundImage:
    "linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px)",
  backgroundSize: "56px 56px",
};

const eyebrow: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 11,
  letterSpacing: ".2em",
  color: "var(--accent)",
  textTransform: "uppercase",
};

const h2: React.CSSProperties = {
  fontSize: 38,
  lineHeight: 1.08,
  letterSpacing: "-.025em",
  fontWeight: 700,
  margin: "20px 0 0",
};

const bodyText: React.CSSProperties = {
  fontSize: 16,
  lineHeight: 1.6,
  color: "rgba(245,245,243,.6)",
  margin: "18px 0 0",
};

function gridCards(cols: number): React.CSSProperties {
  return {
    display: "grid",
    gridTemplateColumns: `repeat(${cols},1fr)`,
    gap: 1,
    background: "rgba(255,255,255,.09)",
    border: "1px solid rgba(255,255,255,.09)",
    borderRadius: 12,
    overflow: "hidden",
  };
}

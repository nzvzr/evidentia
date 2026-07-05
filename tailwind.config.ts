import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        paper: "var(--paper)",
        shell: "var(--shell)",
        panel: "var(--panel)",
        ink: "var(--ink)",
        ink2: "var(--ink2)",
        sub: "var(--sub)",
        line: "var(--line)",
        line2: "var(--line2)",
        accent: "var(--accent)",
        "accent-weak": "var(--accent-weak)",
        ink900: "#0a0a0b",
        ink850: "#0d0d0f",
        ink800: "#0e0e10",
        risk: {
          high: "#c34635",
          med: "#c1852b",
          low: "#8b8b91",
        },
      },
      fontFamily: {
        sans: ["var(--font-archivo)", "system-ui", "sans-serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;

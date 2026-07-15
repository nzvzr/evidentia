import next from "eslint-config-next";

/**
 * Flat config (ESLint 9 / Next 16). Replaces the legacy .eslintrc.json, which
 * the Next 16 toolchain no longer reads.
 */
const config = [
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "backend/**",
      "out/**",
      // Static design reference (vendored HTML/JS mockups), not application code.
      "design-reference/**",
    ],
  },
  ...(Array.isArray(next) ? next : [next]),
  {
    rules: {
      // Next 16 promotes this to an error. It fires on our mount-time hydration
      // effects (fetch-then-setState), which are correct and intentional: the
      // data is only available after mount. Kept as a warning rather than
      // rewriting the data-loading of six components inside a security pass.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
];

export default config;

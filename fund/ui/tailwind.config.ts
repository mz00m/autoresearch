import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        // Editorial serif for headings — paired with system sans body.
        // Source Serif 4 is loaded via next/font in app/layout.tsx.
        serif: ["var(--font-serif)", "Charter", "Georgia", "serif"],
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Text",
          "Segoe UI",
          "Helvetica Neue",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      colors: {
        ink: "#0f1115",
        paper: "#fbfaf6",
        muted: "#6b6f76",
        rule: "#e6e3da",
        // Brand-restrained accent palette
        ok: "#137333",
        watch: "#9a6b00",
        alert: "#9b2226",
        accent: "#1c4f8e",
      },
      letterSpacing: {
        eyebrow: "0.14em",
      },
    },
  },
  plugins: [],
};

export default config;

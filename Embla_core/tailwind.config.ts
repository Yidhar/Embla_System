import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      boxShadow: {
        float: "var(--embla-shadow-float)",
        insetSoft: "var(--embla-shadow-inset)"
      },
      borderRadius: {
        panel: "var(--embla-radius-panel)",
        card: "var(--embla-radius-card)",
        chip: "var(--embla-radius-chip)"
      },
      transitionTimingFunction: {
        embla: "cubic-bezier(0.2, 0.8, 0.2, 1)"
      }
    }
  },
  plugins: []
};

export default config;

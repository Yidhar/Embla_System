import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        embla: {
          base: "var(--embla-bg-base)",
          cool: "var(--embla-bg-cool)",
          text: "var(--embla-text-primary)",
          muted: "var(--embla-text-muted)",
        },
      },
      borderRadius: {
        panel: "var(--embla-radius-panel)",
        card: "var(--embla-radius-card)",
      },
      boxShadow: {
        float: "var(--embla-shadow-float)",
        insetEmbla: "var(--embla-shadow-inset)",
      },
    },
  },
  plugins: [],
};

export default config;

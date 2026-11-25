import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Georgia", "serif"],
      },
      colors: {
        landing: {
          ink: "#0c1210",
          fog: "#e8efe9",
          mist: "#b7c5ba",
          accent: "#1f7a4c",
          "accent-soft": "#2f9a63",
          caution: "#9a7209",
          warn: "#c45c26",
        },
      },
    },
  },
  plugins: [],
};

export default config;

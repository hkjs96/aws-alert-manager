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
        primary: "#004ac6",
        "primary-container": "#2563eb",
        surface: "#f9f9ff",
        error: "#ba1a1a",
        tertiary: "#6a1edb",
      },
    },
  },
  plugins: [],
};

export default config;

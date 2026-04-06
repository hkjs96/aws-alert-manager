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
        accent: "#2563eb",
        surface: "#f8fafc",
        "alarm-ok": "#16a34a",
        "alarm-alarm": "#dc2626",
        "alarm-insufficient": "#d97706",
        "alarm-disabled": "#9ca3af",
        "alarm-muted": "#7c3aed",
        "sev-1": "#dc2626",
        "sev-2": "#ea580c",
        "sev-3": "#d97706",
        "sev-4": "#2563eb",
        "sev-5": "#6b7280",
      },
    },
  },
  plugins: [],
};

export default config;

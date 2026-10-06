/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        background: "#0a0d14",
        card: "#111622",
        cardHover: "#182030",
        primary: {
          DEFAULT: "#6366f1",
          hover: "#4f46e5",
          light: "#818cf8",
        },
        accent: {
          cyan: "#06b6d4",
          emerald: "#10b981",
          purple: "#a855f7",
          amber: "#f59e0b",
        },
        border: "#1f293d",
      },
    },
  },
  plugins: [],
};


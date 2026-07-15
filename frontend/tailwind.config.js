/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      fontFamily: {
        // Body / UI text
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        // Display / headings — a characterful serif for the "registry ledger" identity,
        // used sparingly per the design brief, not for body copy.
        display: ["Fraunces", "ui-serif", "Georgia", "serif"],
        // Record IDs, survey numbers, confidence %, timestamps — ledger/tabular feel.
        mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // --- Waqf DocVerify domain palette ---
        // Named tokens referenced directly (not just via CSS vars) so charts,
        // confidence seals, and status badges can use them predictably.
        "petrol-ink": "#1B3A3A", // primary — deep registry teal, headers & sidebar
        "registry-green": "#2F5D50", // secondary — active states, verified/approved
        brass: "#B08D3E", // accent — seal gold, medium confidence, key actions
        "brass-light": "#D8C089",
        stone: "#EDEFEA", // app background — pale sage-stone paper, not cliché cream
        "stone-dark": "#E2E4DD",
        rust: "#A64B3C", // flagged / low-confidence / error — brick, not terracotta-orange
        ink: "#1C2321", // primary text
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

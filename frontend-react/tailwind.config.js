/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Official EzTech Brand Palette from eztech-official.com
        brand: {
          50: "#F3F6FA",
          100: "#E6F0FF",
          200: "#C8DCFF",
          300: "#9DBDF9",
          400: "#5A8DEE",
          500: "#1E5BD6",
          600: "#1A4EB8",
          700: "#163F95",
          800: "#123170",
          900: "#0E2757",
          950: "#0A1F44",
        },
        // Primary Navy & Backgrounds
        navy: {
          DEFAULT: "#0A1F44",
          light: "#163F95",
          dark: "#071630",
        },
        surface: {
          DEFAULT: "#F3F6FA",
          muted: "#EBF0F7",
        },
        // Official EzTech Gold
        gold: {
          DEFAULT: "#FFC107",
          50: "#FFFBEB",
          100: "#FEF3C6",
          300: "#FFE082",
          400: "#FFD24D",
          500: "#FFC107",
          600: "#C79100",
          700: "#9A6E00",
          dark: "#9A6E00",
          light: "#FFFBEB",
          border: "#FFE082",
        },
        // Backward compatibility aliases
        eztech: {
          DEFAULT: "#1E5BD6",
          hover: "#1A4EB8",
          light: "#E6F0FF",
          border: "#C8DCFF",
        },
        yellow: "#FFC107",
        'light-blue': "#E6F0FF",
        'bg-page': "#F3F6FA",
        background: "#F3F6FA",
        card: "#FFFFFF",
        border: "#E2E8F0",
        foreground: "#0A1F44",
        primary: {
          DEFAULT: "#1E5BD6",
          foreground: "#ffffff"
        },
        muted: {
          DEFAULT: "#F3F6FA",
          foreground: "#64748B"
        },
      },
      fontFamily: {
        sans: ['"Be Vietnam Pro"', 'Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.5rem',
      },
      boxShadow: {
        'card': '0 1px 3px 0 rgba(10, 31, 68, 0.04), 0 1px 2px 0 rgba(10, 31, 68, 0.02)',
        'card-hover': '0 10px 25px -5px rgba(10, 31, 68, 0.08), 0 8px 10px -6px rgba(10, 31, 68, 0.04)',
        'brand': '0 10px 25px -5px rgba(30, 91, 214, 0.25), 0 8px 10px -6px rgba(30, 91, 214, 0.2)',
        'gold': '0 10px 25px -5px rgba(255, 193, 7, 0.3), 0 8px 10px -6px rgba(255, 193, 7, 0.2)',
      }
    },
  },
  plugins: [],
}

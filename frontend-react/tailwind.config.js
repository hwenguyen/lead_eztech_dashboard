/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          DEFAULT: "#0A1F44",
          light: "#162F5F",
        },
        eztech: {
          DEFAULT: "#1E5BD6",
          hover: "#1749B0",
          light: "#EEF4FF",
          border: "#D0E0FF",
        },
        gold: {
          DEFAULT: "#F5B400",
          dark: "#B47D00",
          light: "#FFFBEB",
          border: "#FDE68A",
        },
        yellow: "#F5B400",
        'light-blue': "#EEF4FF",
        'bg-page': "#F8FAFC",
        background: "#F8FAFC",
        card: "#FFFFFF",
        border: "#E2E8F0",
        foreground: "#0F172A",
        primary: {
          DEFAULT: "#1E5BD6",
          foreground: "#ffffff"
        },
        muted: {
          DEFAULT: "#F1F5F9",
          foreground: "#64748B"
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      boxShadow: {
        'card': '0 1px 2px 0 rgba(10, 31, 68, 0.03), 0 1px 3px 0 rgba(10, 31, 68, 0.02)',
        'card-hover': '0 6px 16px -4px rgba(10, 31, 68, 0.06), 0 2px 6px -1px rgba(10, 31, 68, 0.03)',
      }
    },
  },
  plugins: [],
}

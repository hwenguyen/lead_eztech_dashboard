/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: "#0A1F44",
        eztech: "#1E5BD6",
        yellow: "#FFC107",
        'light-blue': "#E6F0FF",
        'bg-page': "#F3F6FA",
        // Keep some standard mappings for backward compatibility if needed, but redefine them
        background: "#F3F6FA",
        card: "#FFFFFF",
        border: "#E5E7EB",
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
      }
    },
  },
  plugins: [],
}

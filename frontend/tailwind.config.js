/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          dark: '#1a1a2e',
          navy: '#16213e',
          accent: '#0f3460',
          highlight: '#e94560',
        }
      }
    },
  },
  plugins: [],
}


/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"DM Sans"', 'system-ui', 'sans-serif'],
      },
      colors: {
        brand: {
          50: '#f0f6fc',
          100: '#dceaf7',
          500: '#2b6cb0',
          600: '#245d9a',
          700: '#1e4d7f',
          900: '#143252',
        },
      },
      boxShadow: {
        soft: '0 1px 3px rgba(15, 23, 42, 0.06), 0 4px 16px rgba(15, 23, 42, 0.04)',
        card: '0 2px 8px rgba(15, 23, 42, 0.06), 0 12px 32px rgba(15, 23, 42, 0.05)',
      },
    },
  },
  plugins: [],
};

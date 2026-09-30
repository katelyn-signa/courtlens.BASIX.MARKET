/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#111111',
        charcoal: '#2b2b2e',
        paper: '#fafafa',
        line: '#e4e4e7',
        success: '#166534',
        warning: '#92400e',
        conflict: '#991b1b',
        info: '#1e40af'
      },
      fontFamily: {
        serif: ['Source Serif 4', 'Georgia', 'serif'],
        sans: ['Inter', 'system-ui', 'sans-serif']
      }
    }
  },
  plugins: []
};

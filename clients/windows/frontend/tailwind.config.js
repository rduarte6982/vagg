/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // VAGG palette — same tokens as the server UI brand book.
        primary: 'oklch(78% 0.16 162)',
        'primary-hover': 'oklch(68% 0.16 162)',
        'primary-ink': 'oklch(28% 0.06 162)',
        vagg: {
          bg: '#0b0d10',
          'bg-2': '#111418',
          'bg-3': '#161a1f',
          line: '#21262d',
          'line-2': '#2c333b',
          ink: '#e8eaed',
          'ink-2': '#b6bbc2',
          'ink-3': '#7a808a',
          'ink-4': '#4a505a',
          signal: 'oklch(78% 0.16 162)',
          warn: 'oklch(78% 0.14 75)',
          crit: 'oklch(70% 0.18 25)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
};

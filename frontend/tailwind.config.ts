import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      /*
       * 颜色一律走 rgb(var(--x-rgb) / <alpha-value>)。
       * 直接写 var(--x) 时，Tailwind 3 解析不出 alpha，
       * bg-primary/10、border-success/30 这类类名会被静默丢弃。
       *
       * 软底不用单独令牌：bg-success/10 + border-success/25 + text-success-deep
       * 就是「浅色软底 + 深字」的完整组合，夜间自动变暗色软底 + 亮字。
       */
      colors: {
        canvas: 'rgb(var(--canvas-rgb) / <alpha-value>)',
        surface: {
          DEFAULT: 'rgb(var(--surface-rgb) / <alpha-value>)',
          raised: 'rgb(var(--surface-raised-rgb) / <alpha-value>)',
          overlay: 'rgb(var(--surface-overlay-rgb) / <alpha-value>)',
        },
        sunken: 'rgb(var(--sunken-rgb) / <alpha-value>)',
        line: {
          DEFAULT: 'rgb(var(--line-rgb) / <alpha-value>)',
          soft: 'rgb(var(--line-soft-rgb) / <alpha-value>)',
          strong: 'rgb(var(--line-strong-rgb) / <alpha-value>)',
        },
        ink: {
          DEFAULT: 'rgb(var(--ink-rgb) / <alpha-value>)',
          muted: 'rgb(var(--ink-muted-rgb) / <alpha-value>)',
          faint: 'rgb(var(--ink-faint-rgb) / <alpha-value>)',
        },
        primary: {
          DEFAULT: 'rgb(var(--primary-rgb) / <alpha-value>)',
          hover: 'rgb(var(--primary-hover-rgb) / <alpha-value>)',
          text: 'rgb(var(--primary-text-rgb) / <alpha-value>)',
        },
        'on-primary': 'rgb(var(--on-primary-rgb) / <alpha-value>)',
        success: {
          DEFAULT: 'rgb(var(--success-rgb) / <alpha-value>)',
          deep: 'rgb(var(--success-deep-rgb) / <alpha-value>)',
        },
        danger: {
          DEFAULT: 'rgb(var(--danger-rgb) / <alpha-value>)',
          deep: 'rgb(var(--danger-deep-rgb) / <alpha-value>)',
        },
        warning: {
          DEFAULT: 'rgb(var(--warning-rgb) / <alpha-value>)',
          deep: 'rgb(var(--warning-deep-rgb) / <alpha-value>)',
        },
        info: {
          DEFAULT: 'rgb(var(--info-rgb) / <alpha-value>)',
          deep: 'rgb(var(--info-deep-rgb) / <alpha-value>)',
        },
        violet: {
          DEFAULT: 'rgb(var(--violet-rgb) / <alpha-value>)',
          deep: 'rgb(var(--violet-deep-rgb) / <alpha-value>)',
        },
      },
      fontFamily: {
        // 现代无衬线：标题与正文同一家族，靠字重与字号分层
        display: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'PingFang SC',
          'HarmonyOS Sans SC',
          'Microsoft YaHei',
          'Noto Sans SC',
          'system-ui',
          'sans-serif',
        ],
        serif: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'PingFang SC',
          'HarmonyOS Sans SC',
          'Microsoft YaHei',
          'Noto Sans SC',
          'system-ui',
          'sans-serif',
        ],
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'PingFang SC',
          'HarmonyOS Sans SC',
          'Microsoft YaHei',
          'Noto Sans SC',
          'system-ui',
          'sans-serif',
        ],
        mono: ['JetBrains Mono', 'Cascadia Mono', 'ui-monospace', 'Menlo', 'monospace'],
      },
      boxShadow: {
        paper: 'var(--shadow-paper)',
        lifted: 'var(--shadow-lifted)',
        overlay: 'var(--shadow-overlay)',
        glow: 'var(--shadow-glow)',
      },
      borderRadius: {
        sm: '6px',
        DEFAULT: '8px',
        md: '10px',
        lg: '14px',
        xl: '18px',
      },
      maxWidth: {
        work: '1200px',
        // 网格页在大屏上要放宽，否则两侧空一大片：useWideContent() 会切到这一档
        wide: '1600px',
      },
      transitionTimingFunction: {
        out: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
      keyframes: {
        rise: {
          from: { opacity: '0', transform: 'translateY(7px)' },
          to: { opacity: '1', transform: 'none' },
        },
        breathe: {
          '0%, 100%': { opacity: '0.35' },
          '50%': { opacity: '1' },
        },
        sweep: {
          from: { transform: 'translateX(-100%)' },
          to: { transform: 'translateX(300%)' },
        },
      },
      animation: {
        rise: 'rise 380ms cubic-bezier(0.22, 1, 0.36, 1) both',
        breathe: 'breathe 1.9s ease-in-out infinite',
        sweep: 'sweep 1.4s cubic-bezier(0.5, 0, 0.5, 1) infinite',
      },
    },
  },
  plugins: [],
} satisfies Config;

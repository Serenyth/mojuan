import { useEffect, useId, useRef, useState } from 'react';
import { cn } from '@/lib/cn';

/** 数字滚动到位。reduce motion 下直接落到终值 */
function useCountUp(target: number, duration = 700) {
  const [value, setValue] = useState(0);
  const raf = useRef(0);

  useEffect(() => {
    const reduce =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    if (reduce) {
      setValue(target);
      return;
    }

    const from = 0;
    const start = performance.now();

    const tick = (now: number) => {
      // 上下界都要钳。只钳上界的话，一旦 now < start（某些环境里 rAF 的
      // 时间戳与 performance.now() 不同源就会这样），p 为负、eased 为负，
      // 插值会一路滑到负数，环上就出现 -378% 这种东西。
      const p = Math.max(0, Math.min(1, (now - start) / duration));
      const eased = 1 - Math.pow(1 - p, 3);
      setValue(from + (target - from) * eased);
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };

    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, duration]);

  return value;
}

export type ChartTone = 'primary' | 'success' | 'warning' | 'info' | 'danger' | 'violet';

/** SVG 描边色：var() 在表现属性里可用（继承自 :root） */
const toneColor: Record<ChartTone, string> = {
  primary: 'var(--primary)',
  success: 'var(--success)',
  warning: 'var(--warning)',
  info: 'var(--info)',
  danger: 'var(--danger)',
  violet: 'var(--violet)',
};

/** 滤镜光晕色：CSS 函数里要 RGB 三元组（--glow 令牌已随「夜读」一起删除） */
const toneRgb: Record<ChartTone, string> = {
  primary: 'var(--primary-rgb)',
  success: 'var(--success-rgb)',
  warning: 'var(--warning-rgb)',
  info: 'var(--info-rgb)',
  danger: 'var(--danger-rgb)',
  violet: 'var(--violet-rgb)',
};

interface ProgressRingProps {
  /** 0–100 */
  value: number;
  size?: number;
  thickness?: number;
  label?: string;
  caption?: string;
  tone?: ChartTone;
  className?: string;
}

export function ProgressRing({
  value,
  size = 96,
  thickness = 7,
  label,
  caption,
  tone = 'primary',
  className,
}: ProgressRingProps) {
  const shown = useCountUp(Math.max(0, Math.min(100, value)));
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - shown / 100);

  return (
    <div className={cn('relative inline-grid place-items-center', className)}>
      <svg width={size} height={size} aria-hidden="true" className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--line)"
          strokeWidth={thickness}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={toneColor[tone]}
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ filter: `drop-shadow(0 0 6px rgb(${toneRgb[tone]} / 0.35))` }}
        />
      </svg>
      <div className="absolute inset-0 grid place-content-center text-center">
        <span className="font-display text-[19px] leading-none text-ink">
          {Math.round(shown)}
          <span className="text-[12px] text-ink-faint">%</span>
        </span>
        {caption ? (
          <span className="mt-1 text-[11px] tracking-wide text-ink-faint">{caption}</span>
        ) : null}
      </div>
      {label ? <span className="sr-only">{label}</span> : null}
    </div>
  );
}

interface SparklineProps {
  points: number[];
  width?: number;
  height?: number;
  tone?: ChartTone;
  className?: string;
}

export function Sparkline({
  points,
  width = 132,
  height = 36,
  tone = 'primary',
  className,
}: SparklineProps) {
  const uid = `sp${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const color = toneColor[tone];

  if (points.length < 2) {
    return <div style={{ width, height }} className={cn('rounded bg-line/25', className)} />;
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const step = width / (points.length - 1);
  const pad = 3;
  const usable = height - pad * 2;

  const coords = points.map((p, i) => [
    i * step,
    pad + usable - ((p - min) / span) * usable,
  ] as const);

  const line = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const area = `${line} L${width} ${height} L0 ${height} Z`;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={cn('overflow-visible', className)} aria-hidden="true">
      <defs>
        <linearGradient id={`${uid}-fill`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${uid}-fill)`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={coords[coords.length - 1][0]} cy={coords[coords.length - 1][1]} r="2.6" fill={color} />
    </svg>
  );
}

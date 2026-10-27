import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info' | 'violet';

const dotTones: Record<Tone, string> = {
  neutral: 'bg-ink-faint',
  accent: 'bg-primary',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
  violet: 'bg-violet',
};

export function StatusDot({
  tone = 'neutral',
  pulse,
  className,
}: {
  tone?: Tone;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        'inline-block h-1.5 w-1.5 shrink-0 rounded-full',
        dotTones[tone],
        pulse && 'animate-breathe',
        className,
      )}
      aria-hidden="true"
    />
  );
}

const barTones: Record<Tone, string> = {
  neutral: 'bg-ink-faint',
  accent: 'bg-primary',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
  violet: 'bg-violet',
};

export function ProgressBar({
  value,
  tone = 'accent',
  className,
}: {
  value: number;
  tone?: Tone;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-line/60', className)}
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={cn(
          'h-full rounded-full transition-[width] duration-700 ease-out',
          barTones[tone],
        )}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('shimmer rounded-md bg-line/40', className)} />;
}

export function SectionLabel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-faint',
        className,
      )}
    >
      {children}
    </div>
  );
}

/** 软色方块：图标瓦、行首图标都用它。bg-X/10 + border-X/25 + text-X-deep
 *  在浅色是「浅底深字」，夜间自动翻成「暗底亮字」，零分支。 */
const softTiles: Record<Tone, string> = {
  neutral: 'bg-sunken text-ink-muted border-line',
  accent: 'bg-primary/10 text-primary-text border-primary/25',
  success: 'bg-success/10 text-success-deep border-success/25',
  warning: 'bg-warning/10 text-warning-deep border-warning/25',
  danger: 'bg-danger/10 text-danger-deep border-danger/25',
  info: 'bg-info/10 text-info-deep border-info/25',
  violet: 'bg-violet/10 text-violet-deep border-violet/25',
};

/** 取软色方块的类名串，供页面自拼图标瓦 */
export const softTile = (tone: Tone): string => softTiles[tone];

/** 增减量胶囊：up 绿 / down 红 */
export function Delta({
  direction = 'up',
  children,
  className,
}: {
  direction?: 'up' | 'down' | 'flat';
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[11.5px] font-bold',
        direction === 'up' && 'bg-success/10 text-success-deep',
        direction === 'down' && 'bg-danger/10 text-danger-deep',
        direction === 'flat' && 'bg-sunken text-ink-muted',
        className,
      )}
    >
      {direction === 'up' ? '↑' : direction === 'down' ? '↓' : null}
      {children}
    </span>
  );
}

export function Stat({
  label,
  value,
  unit,
  hint,
  icon,
  delta,
  tone = 'neutral',
  className,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: ReactNode;
  icon?: ReactNode;
  delta?: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex items-center gap-3.5 rounded-lg border border-line bg-surface px-4 py-3.5 shadow-paper transition-[transform,box-shadow] duration-200 ease-out hover:-translate-y-0.5 hover:shadow-lifted',
        className,
      )}
    >
      {icon ? (
        <span
          className={cn(
            'grid h-11 w-11 shrink-0 place-items-center rounded-[13px] border',
            softTiles[tone],
          )}
        >
          {icon}
        </span>
      ) : null}
      <div className="min-w-0">
        <div className="text-[12.5px] font-semibold text-ink-muted">{label}</div>
        <div className="mt-0.5 flex items-baseline gap-1">
          <span className="text-[25px] font-extrabold leading-none tracking-[-0.02em] text-ink">
            {value}
          </span>
          {unit ? <span className="text-[13px] font-semibold text-ink-muted">{unit}</span> : null}
        </div>
        {hint ? <div className="mt-1 text-[11.5px] text-ink-faint">{hint}</div> : null}
      </div>
      {delta ? <div className="ml-auto shrink-0 pl-2">{delta}</div> : null}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center rounded-lg border border-dashed border-line-strong px-8 py-14 text-center',
        className,
      )}
    >
      {icon ? <div className="mb-4 text-ink-faint/70">{icon}</div> : null}
      <p className="text-[15px] font-semibold text-ink">{title}</p>
      {description ? (
        <p className="mt-2 max-w-sm text-[13px] leading-relaxed text-ink-faint">{description}</p>
      ) : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function Toolbar({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-2 rounded-lg border border-line-soft bg-surface/70 p-2',
        className,
      )}
    >
      {children}
    </div>
  );
}

import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** 悬停浮起，用于可点卡片 */
  interactive?: boolean;
}

export function Card({ className, children, interactive, ...rest }: CardProps) {
  return (
    <div
      className={cn(
        'rounded-lg border border-line bg-surface shadow-paper',
        interactive &&
          'transition-all duration-200 ease-out hover:-translate-y-0.5 hover:border-line-strong hover:shadow-lifted',
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

interface PanelProps {
  title?: string;
  description?: string;
  action?: ReactNode;
  /** 去掉内边距，交给调用方自己排（表格等）；并贯通 flex 高度链，供内部滚动区约束高度 */
  flush?: boolean;
  className?: string;
  children: ReactNode;
}

export function Panel({
  title,
  description,
  action,
  flush,
  className,
  children,
}: PanelProps) {
  return (
    <section className={cn('rounded-lg border border-line bg-surface shadow-paper', className)}>
      {title ? (
        <header className="flex items-start justify-between gap-4 border-b border-line-soft px-5 py-3.5">
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold leading-snug text-ink">{title}</h2>
            {description ? (
              <p className="mt-1 text-[12px] leading-relaxed text-ink-faint">{description}</p>
            ) : null}
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </header>
      ) : null}
      {/* flush 时裸 div 会断掉外层 flex-col 的高度链，内部 flex-1 滚动区会按内容高无限撑开；
          必须让这层 wrapper 自己也成为 flex-1 min-h-0 的列 */}
      <div className={flush ? 'flex min-h-0 flex-1 flex-col' : 'p-5'}>{children}</div>
    </section>
  );
}

type BadgeTone = 'neutral' | 'accent' | 'success' | 'warning' | 'info' | 'danger' | 'violet';

/** 软底 + 深字：浅色下是淡色底深字，夜间自动变暗底亮字 */
const tones: Record<BadgeTone, string> = {
  neutral: 'border-line bg-surface-raised text-ink-muted',
  accent: 'border-primary/30 bg-primary/10 text-primary-text',
  success: 'border-success/30 bg-success/10 text-success-deep',
  warning: 'border-warning/30 bg-warning/10 text-warning-deep',
  info: 'border-info/30 bg-info/10 text-info-deep',
  danger: 'border-danger/30 bg-danger/10 text-danger-deep',
  violet: 'border-violet/30 bg-violet/10 text-violet-deep',
};

export function Badge({
  tone = 'neutral',
  className,
  children,
}: {
  tone?: BadgeTone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-block h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-current border-t-transparent opacity-80',
        className,
      )}
    />
  );
}

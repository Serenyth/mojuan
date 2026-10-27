import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { Spinner } from '@/components/ui/Card';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success-soft' | 'danger-soft';
type Size = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  children: ReactNode;
}

const variants: Record<Variant, string> = {
  primary:
    'border border-primary bg-primary text-on-primary shadow-glow hover:border-primary-hover hover:bg-primary-hover hover:-translate-y-0.5',
  secondary:
    'border border-line bg-surface text-ink shadow-paper hover:border-line-strong hover:bg-surface-raised',
  ghost: 'border border-transparent bg-transparent text-ink-muted hover:bg-surface-raised hover:text-ink',
  danger:
    'border border-danger/40 bg-transparent text-danger hover:border-danger hover:bg-danger hover:text-on-primary',
  'success-soft': 'border border-success/30 bg-success/10 text-success-deep hover:border-success/50',
  'danger-soft': 'border border-danger/30 bg-danger/10 text-danger-deep hover:border-danger/50',
};

const sizes: Record<Size, string> = {
  sm: 'h-8 px-3 text-[13px]',
  md: 'h-9 px-4 text-[13.5px]',
  lg: 'h-11 px-6 text-[15px]',
};

export function Button({
  variant = 'secondary',
  size = 'md',
  loading,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-md font-medium',
        'transition-all duration-200 ease-out active:translate-y-0',
        'disabled:pointer-events-none disabled:opacity-45 focus-ring',
        variants[variant],
        sizes[size],
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
}

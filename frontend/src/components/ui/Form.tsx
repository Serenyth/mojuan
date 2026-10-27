import type {
  InputHTMLAttributes,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
  ReactNode,
} from 'react';
import { cn } from '@/lib/cn';
import { IconChevron } from '@/components/ui/icons';

const base =
  'w-full rounded-md border border-line bg-surface px-3 text-sm text-ink placeholder:text-ink-faint transition-all duration-150 focus-ring hover:border-line-strong';

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(base, 'h-10', className)} {...rest} />;
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(base, 'min-h-[88px] py-2 leading-relaxed', className)} {...rest} />;
}

/** 白底细边 + 右侧自绘箭头，不要浏览器默认样式 */
export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className="relative inline-block w-full">
      <select
        className={cn(base, 'h-10 w-full appearance-none pr-9', className)}
        {...rest}
      >
        {children}
      </select>
      <IconChevron className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
    </span>
  );
}

interface FieldProps {
  label: string;
  hint?: string;
  htmlFor?: string;
  children: ReactNode;
}

export function Field({ label, hint, htmlFor, children }: FieldProps) {
  return (
    <div className="space-y-2">
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-ink-muted">
        {label}
      </label>
      {children}
      {hint ? <p className="text-xs leading-relaxed text-ink-faint">{hint}</p> : null}
    </div>
  );
}

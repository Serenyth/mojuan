import { cn } from '@/lib/cn';

interface SwitchProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}

export function Switch({ checked, onChange, label, disabled }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'focus-ring inline-flex h-5 w-9 shrink-0 items-center rounded-full border px-0.5 transition-colors duration-150',
        checked ? 'justify-end border-primary bg-primary/20' : 'justify-start border-line bg-sunken',
        disabled && 'pointer-events-none opacity-45',
      )}
    >
      <span
        className={cn(
          'h-3.5 w-3.5 rounded-full transition-colors duration-150',
          checked ? 'bg-primary' : 'bg-ink-faint',
        )}
      />
    </button>
  );
}

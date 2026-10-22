import { useTheme } from '@/theme';
import { cn } from '@/lib/cn';
import { IconMoon, IconSun } from '@/components/ui/icons';

/**
 * 日夜切换：右上角悬浮芯片里的单个图标按钮。
 * 浅色下显示月亮（点它进夜间），夜间下显示太阳。
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const dark = theme === 'dark';

  return (
    <button
      type="button"
      title={dark ? '切换到日间' : '切换到夜间'}
      aria-label={dark ? '切换到日间' : '切换到夜间'}
      onClick={() => setTheme(dark ? 'light' : 'dark')}
      className={cn(
        'focus-ring grid h-9 w-9 place-items-center rounded-full border border-line bg-surface text-ink-muted shadow-paper transition-colors hover:text-ink',
        className,
      )}
    >
      {dark ? <IconSun className="h-4.5 w-4.5" /> : <IconMoon className="h-4.5 w-4.5" />}
    </button>
  );
}

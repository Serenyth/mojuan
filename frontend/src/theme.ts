import { useCallback, useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'mojuan-theme';

function readStored(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    return null;
  }
}

/** 浅色是主调（桌面工作台），未手动选过就走日间；夜间仍在，右上角可切 */
export function resolveTheme(): Theme {
  return readStored() ?? 'light';
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(resolveTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* 隐私模式下写不进，忽略即可 */
    }
  }, []);

  return { theme, setTheme };
}

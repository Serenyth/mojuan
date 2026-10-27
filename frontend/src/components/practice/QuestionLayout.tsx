import { useCallback, useState } from 'react';
import { IconGrid, IconList } from '@/components/ui/icons';
import { cn } from '@/lib/cn';

/**
 * 刷题 / 考试作答区的题目排布：一列往下翻，或两列铺成网格一眼扫更多。
 * 偏好只存一份（localStorage），两个页面共用；小屏始终是单列，切换只在大屏有区别。
 */

export type QuestionLayout = 'list' | 'grid';

const STORAGE_KEY = 'mojuan:question-layout';

function readLayout(): QuestionLayout {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'grid' ? 'grid' : 'list';
  } catch {
    return 'list';
  }
}

export function useQuestionLayout(): [QuestionLayout, (next: QuestionLayout) => void] {
  const [layout, setLayout] = useState<QuestionLayout>(readLayout);
  const update = useCallback((next: QuestionLayout) => {
    setLayout(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* 隐私模式写不进去就只记在内存 */
    }
  }, []);
  return [layout, update];
}

/** 题目区外层：列表 → 竖排；网格 → 大屏两列、超宽屏三列，卡片各自高度不拉伸 */
export function questionListClass(layout: QuestionLayout): string {
  return layout === 'grid'
    ? 'grid items-start gap-4 sm:grid-cols-2 2xl:grid-cols-3'
    : 'space-y-6';
}

export function QuestionLayoutToggle({
  value,
  onChange,
  className,
}: {
  value: QuestionLayout;
  onChange: (next: QuestionLayout) => void;
  className?: string;
}) {
  const options: Array<[QuestionLayout, typeof IconList, string]> = [
    ['list', IconList, '列表'],
    ['grid', IconGrid, '网格'],
  ];
  return (
    <div className={cn('flex h-7 items-center rounded-md border border-line bg-sunken p-0.5', className)}>
      {options.map(([key, Icon, label]) => (
        <button
          key={key}
          type="button"
          onClick={() => onChange(key)}
          aria-pressed={value === key}
          title={`${label}布局`}
          className={cn(
            'focus-ring grid h-6 w-6 place-items-center rounded transition-colors',
            value === key ? 'bg-surface text-primary shadow-paper' : 'text-ink-faint hover:text-ink',
          )}
        >
          <Icon className="h-3.5 w-3.5" />
        </button>
      ))}
    </div>
  );
}

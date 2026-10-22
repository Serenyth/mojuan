import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

/**
 * 题目跳转：刷题与考试共用的翻阅导航。
 * 大屏是题流左侧的竖排题号栏，小屏吸底横排——手机上侧边没有位置。
 * 两者不同时出现：底部横排条在 lg 起隐藏，竖排栏在 lg 起才显示。
 *
 * action 是交给侧栏的主动作（交卷 / 结算）：题号一多就自己在栏内滚，
 * 交卷按钮钉在栏底不跟着滚，翻到哪一题都够得着。
 */

export type QuestionStatus = 'unanswered' | 'current' | 'answered' | 'correct' | 'wrong' | 'pending';

export interface RailItem {
  id: string;
  status: QuestionStatus;
}

const STATUS_CLASS: Record<QuestionStatus, string> = {
  unanswered: 'border-line text-ink-faint hover:border-line-strong hover:text-ink-muted',
  current: 'border-primary bg-primary text-on-primary shadow-glow',
  answered: 'border-line-strong bg-sunken text-ink-muted',
  correct: 'border-success/40 bg-success/15 text-success-deep',
  wrong: 'border-danger/40 bg-danger/15 text-danger-deep',
  pending: 'border-warning/40 bg-warning/15 text-warning-deep',
};

const STATUS_TITLE: Record<QuestionStatus, string> = {
  unanswered: '未作答',
  current: '下一题',
  answered: '已作答',
  correct: '已答对',
  wrong: '已答错',
  pending: '待阅卷',
};

/** 题量多时竖向排一长条没法看，按数量自动摊成 1 / 2 / 3 列 */
function railColumns(count: number): 1 | 2 | 3 {
  if (count > 30) return 3;
  if (count > 12) return 2;
  return 1;
}

export function QuestionRail({
  items,
  onJump,
  action,
}: {
  items: RailItem[];
  onJump: (id: string) => void;
  action?: ReactNode;
}) {
  const columns = railColumns(items.length);
  return (
    <nav
      aria-label="题目跳转"
      className={cn(
        'sticky top-20 hidden max-h-[calc(100vh-7rem)] shrink-0 flex-col gap-2 py-1 lg:flex',
        // 单列时只有 36px，塞不下「交卷」两个字，带动作位就放宽到 76px
        columns === 1
          ? action
            ? 'w-[76px]'
            : 'w-9'
          : columns === 2
            ? 'w-[78px]'
            : 'w-[116px]',
      )}
    >
      <div
        className={cn(
          'grid min-h-0 flex-1 content-start justify-items-center gap-1.5 overflow-y-auto',
          columns === 1 ? 'grid-cols-1' : columns === 2 ? 'grid-cols-2' : 'grid-cols-3',
        )}
      >
        {items.map((item, index) => (
          <button
            key={item.id}
            type="button"
            title={`第 ${index + 1} 题 · ${STATUS_TITLE[item.status]}`}
            onClick={() => onJump(item.id)}
            className={cn(
              'focus-ring grid h-8 w-8 place-items-center rounded-lg border font-mono text-[11px] font-bold transition-colors',
              STATUS_CLASS[item.status],
            )}
          >
            {index + 1}
          </button>
        ))}
      </div>
      {action ? <div className="shrink-0 pt-2">{action}</div> : null}
    </nav>
  );
}

export function QuestionJumpBar({
  items,
  onJump,
  action,
}: {
  items: RailItem[];
  onJump: (id: string) => void;
  action?: ReactNode;
}) {
  return (
    <div
      aria-label="底部题目跳转"
      className="sticky bottom-[76px] z-20 mt-8 flex items-center gap-2 border-t border-line bg-canvas/95 py-2.5 backdrop-blur lg:hidden"
    >
      <div className="flex flex-1 gap-1.5 overflow-x-auto">
        {items.map((item, index) => (
          <button
            key={item.id}
            type="button"
            title={`第 ${index + 1} 题 · ${STATUS_TITLE[item.status]}`}
            onClick={() => onJump(item.id)}
            className={cn(
              'focus-ring grid h-7 w-7 shrink-0 place-items-center rounded-lg border font-mono text-[10px] font-bold',
              STATUS_CLASS[item.status],
            )}
          >
            {index + 1}
          </button>
        ))}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

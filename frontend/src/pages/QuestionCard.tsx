import { useMemo } from 'react';
import { Badge } from '@/components/ui/Card';
import { Input, Textarea } from '@/components/ui/Form';
import { cn } from '@/lib/cn';
import { QUESTION_TYPE_LABEL, type Option, type QuestionType } from '@/lib/types';
import type { PracticeQuestion } from '@/lib/api';

/**
 * 题目作答卡：刷题页与考试页共用。
 * 渲染五种题型的作答区，受控组件，答案以 string | string[] | null 归一。
 */

export type AnswerValue = string | string[] | null;

interface QuestionCardProps {
  question: PracticeQuestion;
  index: number;
  value: AnswerValue;
  onChange: (next: AnswerValue) => void;
  disabled?: boolean;
  /** 提交中：作答区暂时不可改，防止连点造成重复提交 */
  pending?: boolean;
  showFooterMeta?: boolean;
  /** 网格布局里每张卡只有半屏宽，收紧内边距与字号 */
  compact?: boolean;
}

function countBlanks(content: string): number {
  return (content.match(/_{2,}/g) ?? []).length;
}

function asKeyList(value: AnswerValue): string[] {
  if (value == null) return [];
  return Array.isArray(value) ? value : [value];
}

export function QuestionCard({
  question,
  index,
  value,
  onChange,
  disabled = false,
  pending = false,
  showFooterMeta = true,
  compact = false,
}: QuestionCardProps) {
  const blankCount = useMemo(() => Math.max(countBlanks(question.content), 1), [question.content]);
  const options: Option[] = question.options ?? [];
  const selected = asKeyList(value);
  const locked = disabled || pending;

  function toggleOption(key: string, multi: boolean) {
    if (multi) {
      onChange(selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key]);
    } else {
      onChange([key]);
    }
  }

  return (
    <article className="rounded-lg border border-line bg-surface shadow-paper">
      <header
        className={cn(
          'flex flex-wrap items-center gap-2 border-b border-line-soft',
          compact ? 'px-4 py-2.5' : 'px-5 py-3.5',
        )}
      >
        <span className="text-[12px] font-bold tracking-[0.02em] text-ink-faint">第 {index} 题</span>
        <Badge tone={TYPE_TONE[question.type]}>{QUESTION_TYPE_LABEL[question.type]}</Badge>
        {question.tags.map((tag) => (
          <Badge key={tag}>{tag}</Badge>
        ))}
      </header>

      <div className={compact ? 'px-4 py-3.5' : 'px-5 py-4'}>
        <p
          className={cn(
            'whitespace-pre-wrap break-anywhere font-semibold leading-[1.65] tracking-[0.01em] text-ink',
            compact ? 'text-[16px]' : 'text-[17.5px]',
          )}
        >
          {question.content}
        </p>

        <div className={compact ? 'mt-4 space-y-2' : 'mt-5 space-y-2.5'}>
          {(question.type === 'single_choice' || question.type === 'true_false') &&
            options.map((option) => (
              <ChoiceRow
                key={option.key}
                option={option}
                shape="radio"
                selected={selected.length === 1 && selected[0] === option.key}
                disabled={locked}
                onSelect={() => toggleOption(option.key, false)}
              />
            ))}

          {question.type === 'multiple_choice' &&
            options.map((option) => (
              <ChoiceRow
                key={option.key}
                option={option}
                shape="checkbox"
                selected={selected.includes(option.key)}
                disabled={locked}
                onSelect={() => toggleOption(option.key, true)}
              />
            ))}

          {question.type === 'fill_blank' &&
            Array.from({ length: blankCount }).map((_, i) => (
              <div key={i} className="flex items-center gap-3">
                <span className="w-14 shrink-0 text-right font-mono text-xs text-ink-faint">
                  第 {i + 1} 空
                </span>
                <Input
                  value={selected[i] ?? ''}
                  disabled={locked}
                  onChange={(event) => {
                    const next = [...selected];
                    next[i] = event.target.value;
                    onChange(next);
                  }}
                  placeholder={`填写第 ${i + 1} 空`}
                />
              </div>
            ))}

          {question.type === 'subjective' && (
            <Textarea
              rows={7}
              value={typeof value === 'string' ? value : ''}
              disabled={locked}
              onChange={(event) => onChange(event.target.value)}
              placeholder="写下你的作答……"
            />
          )}
        </div>
      </div>

      {showFooterMeta && (
        <footer
          className={cn(
            'flex items-center gap-4 border-t border-line-soft text-[12px] text-ink-faint',
            compact ? 'px-4 py-2.5' : 'px-5 py-3',
          )}
        >
          <span className="flex items-center gap-1.5">
            难度
            <span className="flex gap-1">
              {Array.from({ length: 5 }).map((_, i) => (
                <span
                  key={i}
                  className={cn(
                    'h-1.5 w-1.5 rounded-full',
                    i < question.difficulty ? 'bg-warning' : 'bg-line-strong',
                  )}
                />
              ))}
            </span>
          </span>
          {question.explanation ? <span>含解析</span> : null}
        </footer>
      )}
    </article>
  );
}

interface ChoiceRowProps {
  option: Option;
  shape: 'radio' | 'checkbox';
  selected: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

function ChoiceRow({ option, shape, selected, disabled, onSelect }: ChoiceRowProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onSelect}
      className={cn(
        'focus-ring flex w-full items-center gap-3 rounded-md border px-[13px] py-[11px] text-left transition-all duration-150',
        selected
          ? 'border-primary bg-primary/10 text-primary-text'
          : 'border-line text-ink hover:border-primary/40 hover:bg-surface-raised',
        disabled && 'pointer-events-none opacity-60',
      )}
    >
      <span
        className={cn(
          'grid h-[26px] w-[26px] shrink-0 place-items-center rounded-lg border text-[12.5px] font-bold',
          shape === 'radio' ? 'rounded-full' : 'rounded-lg',
          selected
            ? 'border-primary bg-primary text-on-primary'
            : 'border-line-soft bg-sunken text-ink-muted',
        )}
      >
        {option.key}
      </span>
      <span className="break-anywhere text-[14.5px] leading-relaxed">{option.text}</span>
    </button>
  );
}

const TYPE_TONE: Record<QuestionType, 'neutral' | 'accent' | 'success' | 'warning' | 'info' | 'violet'> = {
  single_choice: 'info',
  multiple_choice: 'accent',
  true_false: 'warning',
  fill_blank: 'neutral',
  subjective: 'violet',
};

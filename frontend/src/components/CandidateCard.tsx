import { Badge } from '@/components/ui/Card';
import { cn } from '@/lib/cn';
import { QUESTION_TYPE_LABEL } from '@/lib/types';
import type { CandidateQuestion } from '@/lib/api';

/** 候选题目 + 前端唯一 key（审核勾选列表用） */
export type Candidate = CandidateQuestion & { key: string };

export function Checkbox({
  checked,
  onToggle,
  label,
}: {
  checked: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation();
        onToggle();
      }}
      className={cn(
        'focus-ring grid h-4 w-4 shrink-0 place-items-center rounded-sm border transition-all duration-150',
        checked ? 'border-primary bg-primary text-on-primary' : 'border-line-strong hover:border-primary/60',
      )}
    >
      {checked ? (
        <svg viewBox="0 0 12 12" className="h-3 w-3" aria-hidden="true">
          <path
            d="M2.5 6.5 4.8 8.8 9.5 3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      ) : null}
    </button>
  );
}

export function CandidateCard({
  candidate,
  checked,
  onToggle,
  onRemove,
}: {
  candidate: Candidate;
  checked: boolean;
  onToggle: () => void;
  onRemove?: () => void;
}) {
  const answerText = Array.isArray(candidate.answer)
    ? candidate.answer.filter(Boolean).join('、')
    : String(candidate.answer ?? '');
  const groups = candidate.acceptableAnswers?.filter((group) => group.length) ?? [];

  return (
    <li
      className={cn(
        'rounded-md border bg-surface-raised/40 px-2.5 py-2.5 transition-colors',
        checked ? 'border-line' : 'border-line-soft opacity-60',
      )}
    >
      <div className="flex items-start gap-2.5">
        <span className="pt-0.5">
          <Checkbox checked={checked} onToggle={onToggle} label="导入这道题" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone="info">{QUESTION_TYPE_LABEL[candidate.type] ?? candidate.type}</Badge>
            {candidate.suspect ? <Badge tone="warning">存疑</Badge> : null}
            {candidate.duplicate ? <Badge tone="neutral">重复</Badge> : null}
            {candidate.issues.map((issue) => (
              <Badge key={issue} tone="accent">
                {issue}
              </Badge>
            ))}
          </div>

          <p className="mt-1.5 break-anywhere text-[13px] leading-relaxed text-ink">{candidate.content}</p>

          {candidate.options?.length ? (
            <ul className="mt-1.5 space-y-0.5">
              {candidate.options.map((option) => (
                <li key={option.key} className="flex gap-1.5 text-[12.5px] text-ink-muted">
                  <span className="shrink-0 font-mono text-ink-faint">{option.key}.</span>
                  <span className="min-w-0 break-anywhere">{option.text}</span>
                </li>
              ))}
            </ul>
          ) : null}

          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 break-anywhere text-[11.5px] text-ink-faint">
            <span className="min-w-0">
              答案：<span className="text-ink-muted">{answerText || '未给出'}</span>
            </span>
            {groups.length ? (
              <span className="min-w-0">
                等价：
                <span className="text-ink-muted">
                  {groups.map((group) => group.join(' / ')).join('；')}
                </span>
              </span>
            ) : null}
            <span className="font-mono">置信度 {Math.round(candidate.confidence * 100)}%</span>
            <span className="font-mono">难度 {candidate.difficulty}</span>
            {candidate.tags.length ? (
              <span className="min-w-0">{candidate.tags.map((tag) => `#${tag}`).join(' ')}</span>
            ) : null}
          </div>

          {candidate.explanation ? (
            <p className="mt-1.5 break-anywhere border-l-2 border-line-strong pl-2 text-[12px] leading-relaxed text-ink-faint">
              {candidate.explanation}
            </p>
          ) : null}
        </div>

        {onRemove ? (
          <button
            type="button"
            aria-label="移除这道题"
            onClick={onRemove}
            className="focus-ring shrink-0 rounded px-1 text-ink-faint transition-colors hover:text-danger"
          >
            ×
          </button>
        ) : null}
      </div>
    </li>
  );
}

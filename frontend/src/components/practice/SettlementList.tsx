import { useState } from 'react';
import { Badge } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Form';
import { IconCheck, IconX } from '@/components/ui/icons';
import { cn } from '@/lib/cn';
import { QUESTION_TYPE_LABEL, type Option, type Question, type QuestionType } from '@/lib/types';
import type { PracticeRecordView } from '@/lib/api';
import { questionListClass, type QuestionLayout } from '@/components/practice/QuestionLayout';

/**
 * 结算列表：把做过的题逐条摊开——我的作答、正确答案、解析，
 * 主观题直接在条目里打分写评语，不再有单独的阅卷入口。
 * 可切网格；选择题直接把选项摊开，正确项绿、错选项红、整张未作答的卡变黄。
 */

export interface SettlementEntry {
  question: Question;
  record: PracticeRecordView | null;
}

const TYPE_TONE: Record<QuestionType, 'neutral' | 'accent' | 'success' | 'warning' | 'info' | 'violet'> = {
  single_choice: 'info',
  multiple_choice: 'accent',
  true_false: 'warning',
  fill_blank: 'neutral',
  subjective: 'violet',
};

function keySet(value: unknown): Set<string> {
  if (value == null) return new Set();
  const list = Array.isArray(value) ? value : [value];
  return new Set(list.map(String).filter(Boolean));
}

/** 判断题多数不带选项，补两个出来，好让对错的着色跟选择题一致 */
function optionList(question: Question): Option[] {
  if (question.options?.length) return question.options;
  if (question.type === 'true_false') {
    return [
      { key: 'T', text: '正确' },
      { key: 'F', text: '错误' },
    ];
  }
  return [];
}

function formatAnswer(value: unknown, options?: Option[] | null, multiline = false): string {
  if (value == null) return '（未作答）';
  const list = Array.isArray(value) ? value.map(String) : [String(value)];
  if (options?.length) {
    const text = list
      .map((key) => {
        const option = options.find((item) => item.key === key);
        return option ? `${option.key}. ${option.text}` : key;
      })
      .join('；');
    return text || '未给出';
  }
  const text = list.filter(Boolean).join(multiline ? '\n' : '；');
  return text || '未给出';
}

function StatusBadge({ question, record }: { question: Question; record: PracticeRecordView | null }) {
  if (record == null) return <Badge tone="warning">未作答</Badge>;
  if (record.correct === true) {
    const score = question.type === 'subjective' && record.score != null ? ` · ${record.score}/${record.maxScore} 分` : '';
    return <Badge tone="success">✓ 正确{score}</Badge>;
  }
  if (record.correct === false) {
    const score = question.type === 'subjective' && record.score != null ? ` · ${record.score}/${record.maxScore} 分` : '';
    return <Badge tone="danger">✕ 错误{score}</Badge>;
  }
  return <Badge tone="info">待阅卷</Badge>;
}

/** 选项摊开：正确答案绿、我选错的那项红，其余保持中性 */
function AnswerOptions({ question, record }: { question: Question; record: PracticeRecordView | null }) {
  const options = optionList(question);
  if (!options.length) return null;
  const correct = keySet(question.answer);
  const picked = keySet(record?.userAnswer);

  return (
    <ul className="mt-3 space-y-1.5">
      {options.map((option) => {
        const isCorrect = correct.has(option.key);
        const isPicked = picked.has(option.key);
        const wrongPick = isPicked && !isCorrect;
        return (
          <li
            key={option.key}
            className={cn(
              'flex items-start gap-2 rounded-md border px-2.5 py-2 text-[13.5px] leading-relaxed',
              isCorrect
                ? 'border-success/40 bg-success/10 text-ink'
                : wrongPick
                  ? 'border-danger/40 bg-danger/10 text-ink'
                  : 'border-line-soft bg-surface-raised/40 text-ink-muted',
            )}
          >
            <span
              className={cn(
                'mt-[1px] grid h-[18px] min-w-[18px] place-items-center rounded px-1 font-mono text-[10px] font-bold',
                isCorrect
                  ? 'bg-success text-white'
                  : wrongPick
                    ? 'bg-danger text-white'
                    : 'bg-sunken text-ink-faint',
              )}
            >
              {option.key}
            </span>
            <span className="min-w-0 flex-1 break-anywhere">{option.text}</span>
            {isCorrect ? (
              <IconCheck className="mt-[3px] h-3.5 w-3.5 shrink-0 text-success" />
            ) : wrongPick ? (
              <IconX className="mt-[3px] h-3.5 w-3.5 shrink-0 text-danger" />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export function SettlementList({
  entries,
  layout,
  onGraded,
}: {
  entries: SettlementEntry[];
  layout: QuestionLayout;
  onGraded: (recordId: string, payload: { score: number; comment?: string }) => Promise<unknown>;
}) {
  const grid = layout === 'grid';

  return (
    <div className={questionListClass(layout)}>
      {entries.map(({ question, record }, index) => {
        const unanswered = record == null;
        const options = optionList(question);
        return (
          <article
            key={question.id}
            className={cn(
              'rounded-lg border shadow-paper',
              // 没作答的整张卡变黄：跟「待办」一样的视觉重量，一眼能挑出来
              unanswered ? 'border-warning/50 bg-warning/[0.07]' : 'border-line bg-surface',
            )}
          >
            <header
              className={cn(
                'flex flex-wrap items-center gap-2 border-b border-line-soft',
                grid ? 'px-4 py-2.5' : 'px-5 py-3',
              )}
            >
              <span className="font-mono text-xs text-ink-faint">#{String(index + 1).padStart(2, '0')}</span>
              <Badge tone={TYPE_TONE[question.type]}>{QUESTION_TYPE_LABEL[question.type]}</Badge>
              <StatusBadge question={question} record={record} />
            </header>

            <div className={grid ? 'px-4 py-3.5' : 'px-5 py-4'}>
              <p
                className={cn(
                  'whitespace-pre-wrap break-anywhere font-semibold leading-[1.6] text-ink',
                  grid ? 'text-[16px]' : 'text-[17.5px]',
                )}
              >
                {question.content}
              </p>

              {options.length ? (
                <AnswerOptions question={question} record={record} />
              ) : (
                <div className="mt-3 space-y-1.5 border-t border-line-soft pt-3 text-[13.5px] leading-relaxed">
                  {unanswered ? null : (
                    <p className="text-ink-muted">
                      <span className="mr-1.5 text-[12px] font-bold text-ink-faint">我的作答</span>
                      <span
                        className={cn(
                          'break-anywhere whitespace-pre-wrap',
                          record?.correct === false
                            ? 'font-semibold text-danger-deep'
                            : record?.correct === true
                              ? 'font-semibold text-success-deep'
                              : '',
                        )}
                      >
                        {formatAnswer(record?.userAnswer)}
                      </span>
                    </p>
                  )}
                  <p className="text-ink-muted">
                    <span className="mr-1.5 text-[12px] font-bold text-ink-faint">
                      {question.type === 'subjective' ? '参考答案' : '正确答案'}
                    </span>
                    <span
                      className={cn(
                        'break-anywhere whitespace-pre-wrap font-semibold',
                        // 主观题给的是参考答案，不做对错着色
                        question.type === 'subjective' ? 'text-ink' : 'text-success-deep',
                      )}
                    >
                      {formatAnswer(question.answer, question.options, question.type === 'subjective')}
                    </span>
                  </p>
                </div>
              )}

              {record?.comment || question.explanation ? (
                <div className="mt-3 space-y-1.5 border-t border-line-soft pt-3 text-[13px] leading-[1.75] text-ink-muted">
                  {record?.comment ? (
                    <p>
                      <span className="mr-1.5 text-[12px] font-bold text-ink-faint">评语</span>
                      <span className="break-anywhere">{record.comment}</span>
                    </p>
                  ) : null}
                  {question.explanation ? (
                    <p>
                      <span className="mr-1.5 text-[12px] font-bold text-ink-faint">解析</span>
                      <span className="break-anywhere">{question.explanation}</span>
                    </p>
                  ) : null}
                </div>
              ) : null}

              {record != null && record.correct === null ? (
                <GradeForm record={record} onGraded={onGraded} />
              ) : null}
            </div>
          </article>
        );
      })}
    </div>
  );
}

function GradeForm({
  record,
  onGraded,
}: {
  record: PracticeRecordView;
  onGraded: (recordId: string, payload: { score: number; comment?: string }) => Promise<unknown>;
}) {
  const max = record.maxScore ?? 10;
  const [score, setScore] = useState('');
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    const value = Number(score);
    if (!Number.isFinite(value) || value < 0 || value > max) {
      setError(`得分需在 0 ~ ${max} 之间`);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onGraded(record.id, { score: value, comment: comment.trim() || undefined });
    } catch (err) {
      setError(err instanceof Error ? err.message : '阅卷失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 rounded-md border border-line-soft bg-sunken px-4 py-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="w-28">
          <span className="mb-1 block text-[11.5px] text-ink-faint">得分（满分 {max}）</span>
          <Input
            type="number"
            min={0}
            max={max}
            step={0.5}
            value={score}
            onChange={(event) => setScore(event.target.value)}
            placeholder="0"
            className="h-9"
          />
        </label>
        <label className="min-w-[160px] flex-1">
          <span className="mb-1 block text-[11.5px] text-ink-faint">评语</span>
          <Input
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder="选填"
            className="h-9"
          />
        </label>
        <Button variant="primary" size="sm" disabled={saving || !score} onClick={() => void submit()}>
          {saving ? '提交中…' : '提交阅卷'}
        </Button>
      </div>
      {error ? <p className="mt-2 text-[12px] text-danger-deep">{error}</p> : null}
    </div>
  );
}

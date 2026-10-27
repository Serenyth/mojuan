import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { PageTitle, useWideContent } from '@/components/AppShell';
import { Badge, Panel } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Form';
import { IconCheck, IconX } from '@/components/ui/icons';
import { cn } from '@/lib/cn';
import { QUESTION_TYPE_LABEL, type QuestionType } from '@/lib/types';
import {
  quizApi,
  type AnswerOutcome,
  type Bank,
  type PracticeFinishResult,
  type PracticeOrder,
  type PracticeQuestion,
  type PracticeSessionInfo,
  type PracticeState,
} from '@/lib/api';
import { QuestionCard, type AnswerValue } from '@/pages/QuestionCard';
import { QuestionJumpBar, QuestionRail, type QuestionStatus } from '@/components/practice/QuestionRail';
import {
  QuestionLayoutToggle,
  questionListClass,
  useQuestionLayout,
} from '@/components/practice/QuestionLayout';
import { SettlementList } from '@/components/practice/SettlementList';
import { scrollToElement } from '@/lib/scroll';

/** 刷题引擎：条件筛选组题、向下翻阅作答、结算逐题对照并内联阅卷。 */

const LAST_SESSION_KEY = 'mojuan_last_practice_session';
const DEFAULT_LIMIT = 20;

/** 单选 / 判断：点选即判，不再按一次「提交答案」 */
const INSTANT_TYPES = new Set<string>(['single_choice', 'true_false']);

type View =
  | { kind: 'home' }
  | { kind: 'session' }
  | { kind: 'summary'; result: PracticeFinishResult; history?: boolean };

function isFilled(value: AnswerValue): boolean {
  if (value == null) return false;
  return Array.isArray(value) ? value.some((item) => item.trim()) : value.trim().length > 0;
}

function sessionTitle(session: PracticeSessionInfo): string {
  if (session.mode === 'wrong') return '错题重刷';
  return session.order === 'sequential' ? '顺序刷题' : '随机刷题';
}

/** 正确答案 → 可读文本：选择题映射键到选项原文，填空直接罗列 */
function formatAnswerText(question: PracticeQuestion, answer: string[] | string | null): string | null {
  if (answer == null) return null;
  const keys = (Array.isArray(answer) ? answer : [answer]).filter((item) => item.trim().length > 0);
  if (!keys.length) return null;
  const options = question.options ?? [];
  if (options.length) {
    return keys
      .map((key) => {
        const option = options.find((item) => item.key === key);
        return option ? `${option.key}. ${option.text}` : key;
      })
      .join('，');
  }
  return keys.join(' / ');
}

export function PracticePage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  /** 从概览的记录点进来时带 ?session=<id>，直接铺历史答卷 */
  const historySessionId = searchParams.get('session');

  const [view, setView] = useState<View>({ kind: 'home' });
  const [layout, setLayout] = useQuestionLayout();
  // 网格态才放宽内容区；列表态单列摊太宽反而不好读
  useWideContent(layout === 'grid' && view.kind !== 'home');
  const [banks, setBanks] = useState<Bank[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [scope, setScope] = useState<'all' | 'wrong'>('all');
  const [order, setOrder] = useState<PracticeOrder>('shuffle');
  const [bankId, setBankId] = useState('');
  const pickedBankIsWrongBook =
    banks.find((bank) => bank.id === bankId)?.kind === 'wrongbook';
  const wrongBook = banks.find((bank) => bank.kind === 'wrongbook') ?? null;
  const plainBanks = banks.filter((bank) => bank.kind !== 'wrongbook');
  const [questionType, setQuestionType] = useState<string>('');
  const [tag, setTag] = useState('');
  const [limit, setLimit] = useState(DEFAULT_LIMIT);

  const [state, setState] = useState<PracticeState | null>(null);
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({});
  const [outcomes, setOutcomes] = useState<Record<string, AnswerOutcome>>({});
  const [error, setError] = useState<string | null>(null);
  const [resumable, setResumable] = useState<PracticeState | null>(null);
  const [submittingId, setSubmittingId] = useState<string | null>(null);

  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // 题库与标签
  useEffect(() => {
    void (async () => {
      try {
        const result = await quizApi.listBanks();
        setBanks(result.banks);
        const collected = new Set<string>();
        for (const bank of result.banks) {
          const questions = await quizApi.listQuestions(bank.id, { pageSize: 100 });
          questions.tags.forEach((item) => collected.add(item));
        }
        setTags([...collected].sort());
      } catch {
        /* 题库加载失败不阻塞页面，开始刷题时会再报错 */
      }
    })();
  }, []);

  // 中断恢复：本地记录的会话 ID 尝试恢复
  useEffect(() => {
    const sessionId = window.localStorage.getItem(LAST_SESSION_KEY);
    if (!sessionId) return;
    void (async () => {
      try {
        setResumable(await quizApi.resumeSession(sessionId));
      } catch {
        window.localStorage.removeItem(LAST_SESSION_KEY);
      }
    })();
  }, []);

  const scrollToQuestion = useCallback((id: string) => {
    scrollToElement(cardRefs.current[id]);
  }, []);

  // 历史答卷：把结算页当只读回顾用，不改动会话状态
  useEffect(() => {
    if (!historySessionId) return;
    let alive = true;
    void (async () => {
      try {
        const result = await quizApi.practiceResult(historySessionId);
        if (alive) setView({ kind: 'summary', result, history: true });
      } catch (err) {
        if (!alive) return;
        setError(err instanceof Error ? err.message : '答卷加载失败');
        setView({ kind: 'home' });
      }
    })();
    return () => {
      alive = false;
    };
  }, [historySessionId]);

  /** 用会话 payload 恢复翻页状态：已答的题带回填答案、判分结果与正确答案 */
  const hydrate = useCallback((result: PracticeState) => {
    setState(result);
    const questionMap = new Map((result.questions ?? []).map((question) => [question.id, question]));
    const nextAnswers: Record<string, AnswerValue> = {};
    const nextOutcomes: Record<string, AnswerOutcome> = {};
    for (const record of result.records ?? []) {
      nextAnswers[record.questionId] = (record.userAnswer ?? null) as AnswerValue;
      nextOutcomes[record.questionId] = {
        correct: record.correct,
        score: record.score,
        maxScore: record.maxScore,
        detail: '',
        explanation: questionMap.get(record.questionId)?.explanation ?? null,
        answer: record.answer ?? null,
      };
    }
    setAnswers(nextAnswers);
    setOutcomes(nextOutcomes);
  }, []);

  const startSession = useCallback(
    async (resumeId?: string) => {
      setError(null);
      try {
        const next = resumeId
          ? await quizApi.resumeSession(resumeId)
          : await quizApi.createSession({
              scope,
              order,
              bankId: bankId || undefined,
              filters: {
                ...(questionType ? { type: questionType } : {}),
                ...(tag ? { tag } : {}),
              },
              limit,
            });
        hydrate(next);
        setView({ kind: 'session' });
        setResumable(null);
        window.localStorage.setItem(LAST_SESSION_KEY, next.session.id);
        // 光标指「顺序上的下一道」，从它开始读
        requestAnimationFrame(() => {
          if (next.current) scrollToQuestion(next.current.id);
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : '创建刷题会话失败');
      }
    },
    [scope, order, bankId, questionType, tag, limit, hydrate, scrollToQuestion],
  );

  const submitAnswer = useCallback(
    async (question: PracticeQuestion, answer?: AnswerValue) => {
      if (!state) return;
      const value = answer !== undefined ? answer : answers[question.id];
      if (value == null) return;
      setSubmittingId(question.id);
      setError(null);
      try {
        const result = await quizApi.answerQuestion(state.session.id, {
          questionId: question.id,
          answer: value,
        });
        setState(result);
        setOutcomes((prev) => ({ ...prev, [question.id]: result.outcome }));
        // 答错不跳走：停在原题看解析；答对才顺到顺序上的下一道
        if (result.outcome.correct === true && result.current) {
          scrollToQuestion(result.current.id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : '提交答案失败');
      } finally {
        setSubmittingId(null);
      }
    },
    [state, answers, scrollToQuestion],
  );

  /** 选项变更：单选 / 判断点选即判，其余题型只是记录作答 */
  const handleAnswerChange = useCallback(
    (question: PracticeQuestion, next: AnswerValue) => {
      setAnswers((prev) => ({ ...prev, [question.id]: next }));
      if (outcomes[question.id] != null || next == null) return;
      if (INSTANT_TYPES.has(question.type)) {
        void submitAnswer(question, next);
      }
    },
    [outcomes, submitAnswer],
  );

  const finish = useCallback(async () => {
    if (!state) return;
    setError(null);
    try {
      const result = await quizApi.finishSession(state.session.id);
      window.localStorage.removeItem(LAST_SESSION_KEY);
      setView({ kind: 'summary', result });
    } catch (err) {
      setError(err instanceof Error ? err.message : '结束会话失败');
    }
  }, [state]);

  const abandon = useCallback(() => {
    window.localStorage.removeItem(LAST_SESSION_KEY);
    setResumable(null);
  }, []);

  /* ---------- 结算 ---------- */
  if (view.kind === 'summary') {
    const { result } = view;
    const answered = result.records.length;
    const correct = result.records.filter((record) => record.correct === true).length;
    const pending = result.records.filter((record) => record.correct === null).length;
    const accuracy = answered ? correct / answered : null;
    // 只摊开做过的题
    const entries = result.questions
      .map((question) => ({
        question,
        record: result.records.find((record) => record.questionId === question.id) ?? null,
      }))
      .filter((entry) => entry.record != null);

    async function handleGraded(recordId: string, payload: { score: number; comment?: string }) {
      const graded = await quizApi.gradeReview(recordId, payload);
      setView((current) =>
        current.kind === 'summary'
          ? {
              kind: 'summary',
              result: {
                ...current.result,
                records: current.result.records.map((record) =>
                  record.id === recordId ? graded.record : record,
                ),
              },
            }
          : current,
      );
    }

    return (
      <div className={cn('mx-auto w-full', layout === 'grid' ? 'max-w-[1360px]' : 'max-w-2xl')}>
        <header className="mb-10 text-center">
          <p className="text-[11px] font-bold tracking-[0.3em] text-ink-faint">
            {view.history ? '答卷回顾' : '本轮结算'}
          </p>
          <div className="mt-5 flex items-end justify-center gap-3">
            <span className="text-[44px] font-extrabold leading-none tracking-[-0.02em] text-ink">
              {correct}
              <span className="text-xl font-bold text-ink-faint"> / {answered}</span>
            </span>
            {accuracy != null && (
              <Badge tone={accuracy >= 0.6 ? 'success' : 'warning'}>
                正确率 {Math.round(accuracy * 100)}%
              </Badge>
            )}
          </div>
          <div className="mt-3 flex items-center justify-center gap-2.5">
            <p className="text-[12.5px] text-ink-faint">
              {pending > 0 ? `${pending} 道主观题待给分，在下方题目里直接阅` : '全部题目已判分'}
            </p>
            <QuestionLayoutToggle value={layout} onChange={setLayout} className="hidden sm:flex" />
          </div>
        </header>

        <SettlementList entries={entries} layout={layout} onGraded={handleGraded} />

        <div className="mt-10 flex flex-wrap items-center justify-center gap-2">
          {view.history ? (
            <>
              <Button variant="primary" onClick={() => navigate('/')}>
                返回概览
              </Button>
              <Button
                onClick={() => {
                  navigate('/practice', { replace: true });
                  setView({ kind: 'home' });
                }}
              >
                再刷一轮
              </Button>
            </>
          ) : (
            <Button variant="primary" onClick={() => setView({ kind: 'home' })}>
              再刷一轮
            </Button>
          )}
        </div>
      </div>
    );
  }

  /* ---------- 答题中：向下翻阅 ---------- */
  if (view.kind === 'session' && state) {
    const questions = state.questions ?? [];
    const session = state.session;
    const answeredCount = questions.filter((question) => outcomes[question.id]).length;
    const correctCount = questions.filter((question) => outcomes[question.id]?.correct === true).length;
    const progress = questions.length ? Math.round((answeredCount / questions.length) * 100) : 0;

    const railItems = questions.map((question) => {
      const outcome = outcomes[question.id];
      let status: QuestionStatus = 'unanswered';
      if (outcome) {
        status = outcome.correct === true ? 'correct' : outcome.correct === false ? 'wrong' : 'pending';
      } else if (state.current?.id === question.id) {
        status = 'current';
      }
      return { id: question.id, status };
    });

    return (
      <div
        className={cn(
          'mx-auto flex w-full items-start justify-center gap-10',
          layout === 'grid' ? 'max-w-wide' : 'max-w-5xl',
        )}
      >
        <QuestionRail
          items={railItems}
          onJump={scrollToQuestion}
          action={
            <Button variant="primary" size="sm" className="w-full" onClick={() => void finish()}>
              结算
            </Button>
          }
        />

        <div className={cn('min-w-0 w-full', layout === 'grid' ? 'max-w-[1360px]' : 'max-w-2xl')}>
          <header className="mb-10 text-center">
            <p className="text-[11px] font-bold tracking-[0.3em] text-ink-faint">刷题中</p>
            <h1 className="mt-3 text-[24px] font-extrabold tracking-[-0.01em] text-ink">
              {sessionTitle(session)}
            </h1>
            <div className="mt-2 flex items-center justify-center gap-2.5">
              <span className="font-mono text-[12px] text-ink-faint">
                已答 {answeredCount} / {questions.length} · 答对 {correctCount}
              </span>
              <QuestionLayoutToggle value={layout} onChange={setLayout} />
            </div>
            <div className="mx-auto mt-5 h-[3px] w-56 max-w-full overflow-hidden rounded-full bg-sunken">
              <div
                className="h-full rounded-full bg-primary transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          </header>

          {error && <ErrorNote message={error} onClose={() => setError(null)} />}

          <div className={questionListClass(layout)}>
            {questions.map((question, index) => {
              const outcome = outcomes[question.id];
              const value = answers[question.id] ?? null;
              return (
                <div
                  key={question.id}
                  ref={(node) => {
                    cardRefs.current[question.id] = node;
                  }}
                  className="scroll-mt-8"
                >
                  <QuestionCard
                    question={question}
                    index={index + 1}
                    value={value}
                    onChange={(next) => handleAnswerChange(question, next)}
                    disabled={outcome != null}
                    pending={submittingId === question.id}
                    compact={layout === 'grid'}
                  />

                  {outcome ? (
                    <OutcomeNote question={question} outcome={outcome} />
                  ) : INSTANT_TYPES.has(question.type) ? (
                    submittingId === question.id ? (
                      <p className="mt-3 text-right text-[12px] text-ink-faint">判分中…</p>
                    ) : null
                  ) : (
                    <div className="mt-3 flex justify-end">
                      <Button
                        variant="primary"
                        size="sm"
                        disabled={!isFilled(value)}
                        loading={submittingId === question.id}
                        onClick={() => void submitAnswer(question)}
                      >
                        提交答案
                      </Button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="mt-12 border-t border-line-soft pt-8 text-center">
            <p className="text-[13px] text-ink-faint">
              共 {questions.length} 题 · 已答 {answeredCount}
              {answeredCount < questions.length ? ' · 未作答不计入成绩' : ''}
            </p>
          </div>

          <QuestionJumpBar
            items={railItems}
            onJump={scrollToQuestion}
            action={
              <Button variant="primary" size="sm" onClick={() => void finish()}>
                结算
              </Button>
            }
          />
        </div>
      </div>
    );
  }

  /* ---------- 条件筛选 ---------- */
  return (
    <div className="mx-auto max-w-3xl">
      <PageTitle title="刷题" subtitle="按条件组一套题，开始训练" />

      {error && <ErrorNote message={error} onClose={() => setError(null)} />}

      {resumable && (
        <Panel className="mb-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-[13px] text-ink">有未完成的刷题会话</p>
              <p className="mt-1 text-xs text-ink-faint">
                {resumable.session.answered} / {resumable.session.total} 题 ·{' '}
                {sessionTitle(resumable.session)}
              </p>
            </div>
            <div className="flex gap-2">
              <Button variant="primary" size="sm" onClick={() => void startSession(resumable.session.id)}>
                继续刷题
              </Button>
              <Button size="sm" variant="ghost" onClick={abandon}>
                放弃
              </Button>
            </div>
          </div>
        </Panel>
      )}

      <Panel title="抽题条件">
        <div className="space-y-5">
          <div>
            <FieldLabel>范围</FieldLabel>
            <Segmented
              value={scope}
              onChange={setScope}
              options={[
                { value: 'all', label: '全部题目' },
                { value: 'wrong', label: '错题' },
              ]}
            />
          </div>

          <div className="flex flex-wrap items-end gap-4">
            <label className="w-48">
              <FieldLabel>题库</FieldLabel>
              <Select value={bankId} onChange={(event) => setBankId(event.target.value)}>
                <option value="">全部题库</option>
                {/* 内置错题本置顶单列一组 */}
                {wrongBook ? (
                  <optgroup label="内置">
                    <option value={wrongBook.id}>错题本（{wrongBook.questionCount ?? 0}）</option>
                  </optgroup>
                ) : null}
                {plainBanks.length ? (
                  <optgroup label="题库">
                    {plainBanks.map((bank) => (
                      <option key={bank.id} value={bank.id}>
                        {bank.name}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
              </Select>
              {pickedBankIsWrongBook ? (
                <span className="mt-1 block text-[11.5px] text-ink-faint">
                  错题本只抽还没掌握的错题
                </span>
              ) : null}
            </label>

            <label className="w-36">
              <FieldLabel>题型</FieldLabel>
              <Select value={questionType} onChange={(event) => setQuestionType(event.target.value)}>
                <option value="">全部题型</option>
                {(Object.keys(QUESTION_TYPE_LABEL) as QuestionType[]).map((type) => (
                  <option key={type} value={type}>
                    {QUESTION_TYPE_LABEL[type]}
                  </option>
                ))}
              </Select>
            </label>

            <label className="w-48">
              <FieldLabel>标签</FieldLabel>
              <Select value={tag} onChange={(event) => setTag(event.target.value)}>
                <option value="">全部标签</option>
                {tags.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </Select>
            </label>

            <label className="w-28">
              <FieldLabel>题量</FieldLabel>
              <Input
                type="number"
                min={1}
                max={100}
                value={limit}
                onChange={(event) => setLimit(Math.max(1, Math.min(100, Number(event.target.value) || DEFAULT_LIMIT)))}
              />
            </label>
          </div>

          <div>
            <FieldLabel>方式</FieldLabel>
            <Segmented
              value={order}
              onChange={setOrder}
              options={[
                { value: 'shuffle', label: '随机刷题' },
                { value: 'sequential', label: '顺序刷题' },
              ]}
            />
          </div>

          <div className="flex justify-end pt-1">
            <Button variant="primary" onClick={() => void startSession()}>
              开始刷题
            </Button>
          </div>
        </div>
      </Panel>
    </div>
  );
}

function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="mb-1.5 block text-[13px] text-ink-muted">{children}</span>;
}

function Segmented<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (next: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <div className="inline-flex gap-1 rounded-lg border border-line bg-sunken p-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            'focus-ring rounded-md px-4 py-1.5 text-[13px] font-semibold transition-colors',
            value === option.value ? 'bg-surface text-ink shadow-paper' : 'text-ink-muted hover:text-ink',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function OutcomeNote({ question, outcome }: { question: PracticeQuestion; outcome: AnswerOutcome }) {
  const answerText = formatAnswerText(question, outcome.answer);
  return (
    <div
      className={cn(
        'mt-3 rounded-md border px-4 py-3',
        outcome.correct === true && 'border-success/30 bg-success/10',
        outcome.correct === false && 'border-danger/30 bg-danger/10',
        outcome.correct === null && 'border-info/30 bg-info/10',
      )}
    >
      <div className="flex flex-wrap items-center gap-2.5">
        <span
          className={cn(
            'flex items-center gap-1.5 text-[14px] font-bold',
            outcome.correct === true && 'text-success-deep',
            outcome.correct === false && 'text-danger-deep',
            outcome.correct === null && 'text-info-deep',
          )}
        >
          {outcome.correct === true ? (
            <>
              <IconCheck className="h-4 w-4" />
              回答正确
            </>
          ) : outcome.correct === false ? (
            <>
              <IconX className="h-4 w-4" />
              {outcome.detail || '回答错误'}
            </>
          ) : (
            '待阅卷'
          )}
        </span>
        {outcome.maxScore != null && outcome.correct === null && (
          <span className="text-[11.5px] text-ink-faint">满分 {outcome.maxScore} 分 · 结算时给分</span>
        )}
      </div>
      {answerText && (
        <p className="mt-2 break-anywhere border-t border-line/60 pt-2 text-[13px] leading-[1.75] text-ink-muted">
          <span className="mr-1 text-[12px] font-bold text-ink-faint">
            {question.type === 'subjective' ? '参考答案' : '正确答案'}
          </span>
          <span className="text-ink">{answerText}</span>
        </p>
      )}
      {outcome.explanation && (
        <p className="mt-2 break-anywhere border-t border-line/60 pt-2 text-[13px] leading-[1.75] text-ink-muted">
          <span className="mr-1 text-[12px] font-bold text-ink-faint">解析</span>
          {outcome.explanation}
        </p>
      )}
    </div>
  );
}

function ErrorNote({ message, onClose }: { message: string; onClose: () => void }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-4 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-[13px] text-danger-deep">
      <span className="break-anywhere">{message}</span>
      <button type="button" onClick={onClose} className="focus-ring shrink-0 text-ink-faint hover:text-ink">
        ✕
      </button>
    </div>
  );
}

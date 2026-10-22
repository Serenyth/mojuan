import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { PageTitle, useWideContent } from '@/components/AppShell';
import { Badge, Panel } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Field, Input, Select } from '@/components/ui/Form';
import { Switch } from '@/components/ui/Switch';
import { Portal } from '@/components/ui/Portal';
import { cn } from '@/lib/cn';
import { IconClock } from '@/components/ui/icons';
import { QUESTION_TYPE_LABEL, type QuestionType } from '@/lib/types';
import {
  quizApi,
  type Bank,
  type ExamInfo,
  type ExamResult,
  type ExamTemplate,
  type PracticeQuestion,
  type TemplateInput,
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

/**
 * 考试：试卷（即可复用模板）列表 → 开考 → 限时翻阅作答 → 交卷出分并逐题对照阅卷。
 * 模板管理已并入本页：试卷的新建 / 编辑 / 删除都在列表页完成，不再有独立入口。
 */

const ACTIVE_EXAM_KEY = 'mojuan_active_exam';

const TYPE_ORDER: QuestionType[] = [
  'single_choice',
  'multiple_choice',
  'true_false',
  'fill_blank',
  'subjective',
];

type View =
  | { kind: 'pick' }
  | { kind: 'taking'; exam: ExamInfo; questions: PracticeQuestion[] }
  | { kind: 'result'; result: ExamResult; history?: boolean };

function useCountdown(deadline: string | null): number | null {
  const [remaining, setRemaining] = useState<number | null>(null);
  useEffect(() => {
    if (!deadline) return;
    const tick = () => setRemaining(Math.max(0, new Date(deadline).getTime() - Date.now()));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [deadline]);
  return remaining;
}

function formatCountdown(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (value: number) => String(value).padStart(2, '0');
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
}

function isFilled(value: AnswerValue): boolean {
  if (value == null) return false;
  return Array.isArray(value) ? value.some((item) => item.trim()) : value.trim().length > 0;
}

function distributionSummary(paper: ExamTemplate): string {
  return TYPE_ORDER.filter((type) => paper.typeDistribution[type])
    .map((type) => `${QUESTION_TYPE_LABEL[type]}×${paper.typeDistribution[type]}`)
    .join(' · ');
}

export function ExamPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const presetPaperId = searchParams.get('template');
  /** 从概览的记录点进来时带 ?exam=<id>，直接铺历史答卷 */
  const historyExamId = searchParams.get('exam');

  const [view, setView] = useState<View>({ kind: 'pick' });
  const [resultLayout, setResultLayout] = useQuestionLayout();
  // 结果页走网格时放宽内容区，列表态保持 1200 的阅读宽度
  useWideContent(view.kind === 'result' && resultLayout === 'grid');
  const [prefilledAnswers, setPrefilledAnswers] = useState<Record<string, AnswerValue>>({});
  const [papers, setPapers] = useState<ExamTemplate[] | null>(null);
  const [banks, setBanks] = useState<Bank[]>([]);
  const [editing, setEditing] = useState<ExamTemplate | 'new' | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [paperManagerOpen, setPaperManagerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);

  // 恢复进行中的考试（快照端点不返回答案）；从记录点进来回顾答卷时不恢复
  useEffect(() => {
    if (historyExamId) return;
    const examId = window.localStorage.getItem(ACTIVE_EXAM_KEY);
    if (!examId) return;
    void (async () => {
      try {
        const snapshot = await quizApi.examSnapshot(examId);
        if (snapshot.exam.status === 'ongoing') {
          const prefilled: Record<string, AnswerValue> = {};
          for (const record of snapshot.records) {
            if (record.userAnswer != null) prefilled[record.questionId] = record.userAnswer as AnswerValue;
          }
          setPrefilledAnswers(prefilled);
          setView({ kind: 'taking', exam: snapshot.exam, questions: snapshot.questions });
        } else {
          const result = await quizApi.examResult(examId);
          setView({ kind: 'result', result });
        }
      } catch {
        window.localStorage.removeItem(ACTIVE_EXAM_KEY);
      }
    })();
  }, [historyExamId]);

  // 历史答卷：只读回顾，不动 ACTIVE_EXAM_KEY
  useEffect(() => {
    if (!historyExamId) return;
    let alive = true;
    void (async () => {
      try {
        const result = await quizApi.examResult(historyExamId);
        if (alive) setView({ kind: 'result', result, history: true });
      } catch (err) {
        if (!alive) return;
        setError(err instanceof Error ? err.message : '答卷加载失败');
      }
    })();
    return () => {
      alive = false;
    };
  }, [historyExamId]);

  const loadPapers = useCallback(async () => {
    try {
      const [templateResult, bankResult] = await Promise.all([
        quizApi.listTemplates(),
        quizApi.listBanks(),
      ]);
      setPapers(templateResult.templates);
      setBanks(bankResult.banks);
    } catch (err) {
      setError(err instanceof Error ? err.message : '试卷加载失败');
      setPapers([]);
    }
  }, []);

  useEffect(() => {
    if (view.kind === 'pick') void loadPapers();
  }, [view.kind, loadPapers]);

  async function handleStart(paperId: string) {
    setStarting(paperId);
    setError(null);
    try {
      const result = await quizApi.startExam({ templateId: paperId });
      window.localStorage.setItem(ACTIVE_EXAM_KEY, result.exam.id);
      setView({ kind: 'taking', exam: result.exam, questions: result.questions });
    } catch (err) {
      setError(err instanceof Error ? err.message : '开考失败');
    } finally {
      setStarting(null);
    }
  }

  async function handleDelete(id: string) {
    try {
      await quizApi.deleteTemplate(id);
      setPendingDelete(null);
      await loadPapers();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    }
  }

  /** 结算页内联阅卷：阅完重新拉一次结果，分数与记录一起刷新 */
  async function handleGraded(recordId: string, payload: { score: number; comment?: string }) {
    if (view.kind !== 'result') return;
    setError(null);
    try {
      await quizApi.gradeReview(recordId, payload);
      const refreshed = await quizApi.examResult(view.result.exam.id);
      setView({ kind: 'result', result: refreshed });
    } catch (err) {
      setError(err instanceof Error ? err.message : '阅卷失败');
      throw err;
    }
  }

  /* ---------- 试卷选择（模板即试卷） ---------- */
  if (view.kind === 'pick') {
    return (
      <div>
        <div className="mb-5 flex items-end justify-between gap-4">
          <PageTitle title="模拟考试" subtitle="选择试卷开考，限时作答后自动出分" />
          <div className="flex items-center gap-2">
            <Button variant="ghost" className="text-danger" onClick={() => setPaperManagerOpen(true)}>
              删除试卷
            </Button>
            <Button variant="primary" onClick={() => setEditing('new')}>
              新建试卷
            </Button>
          </div>
        </div>

        {error && <ErrorNote message={error} onClose={() => setError(null)} />}

        {papers === null ? (
          <p className="text-[13px] text-ink-faint">载入中…</p>
        ) : papers.length === 0 ? (
          <Panel>
            <p className="py-8 text-center text-[13px] text-ink-faint">
              还没有试卷，点击右上角「新建试卷」创建第一份
            </p>
          </Panel>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {papers.map((paper) => (
              <article
                key={paper.id}
                className={cn(
                  'rounded-lg border bg-surface p-5 shadow-paper transition-all duration-150',
                  paper.id === presetPaperId
                    ? 'border-primary shadow-glow'
                    : 'border-line hover:-translate-y-0.5 hover:border-line-strong hover:shadow-lifted',
                )}
              >
                <header className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-[15px] font-semibold text-ink">{paper.name}</h3>
                    <p className="mt-1 text-xs text-ink-faint">
                      {paper.scopeBankId
                        ? banks.find((bank) => bank.id === paper.scopeBankId)?.name ?? '指定题库'
                        : '不限题库'}
                      {paper.scopeTags.length > 0 && ` · 标签 ${paper.scopeTags.join('、')}`}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Badge tone={paper.isShared ? 'info' : 'neutral'}>
                      {paper.isShared ? '共享' : '私有'}
                    </Badge>
                    {paper.shuffle && <Badge tone="neutral">乱序</Badge>}
                  </div>
                </header>

                <dl className="mt-4 space-y-1.5 text-[13px]">
                  <div className="flex gap-2">
                    <dt className="w-16 shrink-0 text-ink-faint">题型分布</dt>
                    <dd className="text-ink-muted">{distributionSummary(paper)}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-16 shrink-0 text-ink-faint">总题量</dt>
                    <dd className="font-mono text-ink-muted">{paper.totalCount} 题</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-16 shrink-0 text-ink-faint">时长</dt>
                    <dd className="font-mono text-ink-muted">{paper.durationMinutes} 分钟</dd>
                  </div>
                </dl>

                <footer className="mt-4 flex items-center justify-between border-t border-line pt-4">
                  <div className="flex gap-1">
                    <Button size="sm" onClick={() => setEditing(paper)}>
                      编辑
                    </Button>
                    {pendingDelete === paper.id ? (
                      <>
                        <Button variant="danger" size="sm" onClick={() => void handleDelete(paper.id)}>
                          确认删除
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setPendingDelete(null)}>
                          取消
                        </Button>
                      </>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-danger"
                        onClick={() => setPendingDelete(paper.id)}
                      >
                        删除
                      </Button>
                    )}
                  </div>
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={starting !== null}
                    onClick={() => void handleStart(paper.id)}
                  >
                    {starting === paper.id ? '组卷中…' : '开考'}
                  </Button>
                </footer>
              </article>
            ))}
          </div>
        )}

        {editing && (
          <PaperEditorModal
            paper={editing}
            banks={banks}
            onClose={() => setEditing(null)}
            onSaved={async () => {
              setEditing(null);
              await loadPapers();
            }}
          />
        )}

        {paperManagerOpen && papers && (
          <PaperDeleteModal
            papers={papers}
            onClose={() => setPaperManagerOpen(false)}
            onDeleted={async () => {
              setPaperManagerOpen(false);
              await loadPapers();
            }}
          />
        )}
      </div>
    );
  }

  /* ---------- 答题中：向下翻阅 ---------- */
  if (view.kind === 'taking') {
    return (
      <TakingExam
        exam={view.exam}
        questions={view.questions}
        initialAnswers={prefilledAnswers}
        onSubmitted={(result) => setView({ kind: 'result', result })}
        onError={(message) => setError(message)}
      />
    );
  }

  /* ---------- 结果：逐题对照 + 内联阅卷 ---------- */
  const { result } = view;
  const { exam, scores } = result;
  const entries = result.questions.map((question) => ({
    question,
    record: result.records.find((record) => record.questionId === question.id) ?? null,
  }));

  const statusBadge =
    exam.status === 'grading' ? (
      <Badge tone="warning">阅卷中</Badge>
    ) : exam.status === 'graded' ? (
      <Badge tone="success">已出分</Badge>
    ) : (
      <Badge tone="info">已交卷</Badge>
    );

  return (
    <div className={cn('mx-auto w-full', resultLayout === 'grid' ? 'max-w-[1360px]' : 'max-w-2xl')}>
      <header className="mb-10 text-center">
        <p className="text-[11px] font-bold tracking-[0.3em] text-ink-faint">考试结果</p>
        <h1 className="mt-3 text-[26px] font-extrabold tracking-[-0.01em] text-ink">
          {exam.templateName ?? '考试结果'}
        </h1>
        <div className="mt-3 flex items-center justify-center gap-2">
          {statusBadge}
          <span className="text-[12px] text-ink-faint">共 {exam.questionCount} 题</span>
          <QuestionLayoutToggle
            value={resultLayout}
            onChange={setResultLayout}
            className="hidden sm:flex"
          />
        </div>
      </header>

      {error && <ErrorNote message={error} onClose={() => setError(null)} />}

      <div className="mb-6 grid grid-cols-3 gap-3">
        <ScoreCard label="客观题" value={scores.objectiveScore} max={scores.objectiveMax} tone="info" />
        <ScoreCard
          label="主观题"
          value={scores.subjectiveScore}
          max={scores.subjectiveMax}
          tone="warning"
          hint={
            scores.pendingSubjective > 0
              ? `${scores.gradedSubjective}/${scores.subjectiveCount} 已阅`
              : undefined
          }
        />
        <ScoreCard label="总分" value={scores.totalScore} max={scores.objectiveMax + scores.subjectiveMax} tone="accent" />
      </div>

      {scores.pendingSubjective > 0 && (
        <p className="mb-5 text-[13px] text-ink-muted">
          还有 {scores.pendingSubjective} 道主观题待给分，在下方题目里直接阅卷。
        </p>
      )}

      <SettlementList entries={entries} layout={resultLayout} onGraded={handleGraded} />

      <div className="mt-10 flex flex-wrap items-center justify-center gap-2">
        {view.history ? (
          <>
            <Button variant="primary" onClick={() => navigate('/')}>
              返回概览
            </Button>
            <Button
              onClick={() => {
                navigate('/exam', { replace: true });
                setView({ kind: 'pick' });
              }}
            >
              返回试卷列表
            </Button>
          </>
        ) : (
          <Button
            onClick={() => {
              window.localStorage.removeItem(ACTIVE_EXAM_KEY);
              setView({ kind: 'pick' });
            }}
          >
            返回试卷列表
          </Button>
        )}
      </div>
    </div>
  );
}

function TakingExam({
  exam,
  questions,
  initialAnswers,
  onSubmitted,
  onError,
}: {
  exam: ExamInfo;
  questions: PracticeQuestion[];
  initialAnswers?: Record<string, AnswerValue>;
  onSubmitted: (result: ExamResult) => void;
  onError: (message: string) => void;
}) {
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>(initialAnswers ?? {});
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [layout, setLayout] = useQuestionLayout();
  useWideContent(layout === 'grid');
  const remaining = useCountdown(exam.deadline);
  const expired = remaining === 0;
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const answeredCount = questions.filter((question) => isFilled(answers[question.id] ?? null)).length;
  const firstUnanswered = questions.find((question) => !isFilled(answers[question.id] ?? null));

  const railItems = questions.map((question) => {
    const filled = isFilled(answers[question.id] ?? null);
    let status: QuestionStatus = 'unanswered';
    if (filled) status = 'answered';
    else if (firstUnanswered?.id === question.id) status = 'current';
    return { id: question.id, status };
  });

  const scrollToQuestion = useCallback((id: string) => {
    scrollToElement(cardRefs.current[id]);
  }, []);

  // 挂载时定位到第一道未作答的题
  useEffect(() => {
    if (!firstUnanswered) return;
    const id = firstUnanswered.id;
    const timer = requestAnimationFrame(() => scrollToQuestion(id));
    return () => cancelAnimationFrame(timer);
    // 只在开考 / 恢复时定位一次，之后交给用户自己翻
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmit() {
    setSubmitting(true);
    try {
      await quizApi.submitExam(exam.id, {
        answers: questions.map((question) => ({
          questionId: question.id,
          answer: answers[question.id] ?? null,
        })),
      });
      // 交卷后取完整结果（含逐题记录与答案）
      const full = await quizApi.examResult(exam.id);
      onSubmitted(full);
    } catch (err) {
      onError(err instanceof Error ? err.message : '交卷失败');
    } finally {
      setSubmitting(false);
      setConfirming(false);
    }
  }

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
          <Button variant="primary" size="sm" className="w-full" onClick={() => setConfirming(true)}>
            交卷
          </Button>
        }
      />

      <div className={cn('min-w-0 w-full', layout === 'grid' ? 'max-w-[1360px]' : 'max-w-2xl')}>
        {/* 状态条吸顶：往下翻几十题也看得到剩余时间与进度，但只占一行 */}
        <div className="sticky top-[60px] z-30 mb-6 flex items-center gap-2.5 rounded-xl border border-line bg-surface/90 px-3 py-1.5 shadow-paper backdrop-blur-xl">
          <IconClock className="h-4 w-4 shrink-0 text-ink-faint" />
          <span
            className={cn(
              'shrink-0 font-mono text-[15px] font-bold tabular-nums',
              expired ? 'text-danger' : remaining != null && remaining < 60000 ? 'text-warning' : 'text-ink',
            )}
          >
            {remaining == null ? '--:--' : formatCountdown(remaining)}
          </span>
          {expired ? <Badge tone="danger">已到时</Badge> : null}
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink-muted">
            {exam.templateName ?? '考试中'}
          </span>
          <span className="shrink-0 font-mono text-[11.5px] text-ink-muted">
            已答 {answeredCount}/{questions.length}
          </span>
          <div className="hidden h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-sunken sm:block">
            <div
              className="h-full rounded-full bg-primary transition-all duration-500"
              style={{ width: `${questions.length ? (answeredCount / questions.length) * 100 : 0}%` }}
            />
          </div>
          <QuestionLayoutToggle value={layout} onChange={setLayout} className="hidden shrink-0 sm:flex" />
        </div>

        <div className={questionListClass(layout)}>
          {questions.map((question, index) => {
            const filled = isFilled(answers[question.id] ?? null);
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
                  value={answers[question.id] ?? null}
                  onChange={(next) => setAnswers({ ...answers, [question.id]: next })}
                  compact={layout === 'grid'}
                />
                {filled ? (
                  <p className="mt-2 text-right text-[11.5px] font-semibold text-success-deep">✓ 已作答</p>
                ) : null}
              </div>
            );
          })}
        </div>

        <div className="mt-12 border-t border-line-soft pt-8 text-center">
          <p className="text-[13px] text-ink-faint">
            共 {questions.length} 题 · 已答 {answeredCount}
            {answeredCount < questions.length ? ' · 未作答按错误计分' : ''}
          </p>
        </div>

        <QuestionJumpBar
          items={railItems}
          onJump={scrollToQuestion}
          action={
            <Button variant="primary" size="sm" onClick={() => setConfirming(true)}>
              交卷
            </Button>
          }
        />
      </div>

      {confirming && (
        <Portal>
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-canvas/80 p-6"
          onClick={(event) => {
            if (event.target === event.currentTarget) setConfirming(false);
          }}
        >
          <div className="w-full max-w-sm rounded-lg border border-line bg-surface p-6 shadow-overlay">
            <h2 className="text-[15px] font-semibold text-ink">确认交卷</h2>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-muted">
              已答 {answeredCount} / {questions.length} 题。未作答的题目按错误计分，交卷后客观题立即出分，主观题在结果页阅卷。
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button onClick={() => setConfirming(false)}>再检查一下</Button>
              <Button variant="primary" disabled={submitting} onClick={() => void handleSubmit()}>
                {submitting ? '交卷中…' : '确认交卷'}
              </Button>
            </div>
          </div>
        </div>
        </Portal>
      )}
    </div>
  );
}

/** 试卷批量删除：一次列全，多选后二次确认 */
function PaperDeleteModal({
  papers,
  onClose,
  onDeleted,
}: {
  papers: ExamTemplate[];
  onClose: () => void;
  onDeleted: () => void | Promise<void>;
}) {
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pickedPapers = papers.filter((paper) => picked.has(paper.id));

  function toggle(id: string) {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setPicked(next);
    setArmed(false);
  }

  async function handleDelete() {
    if (!picked.size || busy) return;
    if (!armed) {
      setArmed(true);
      return;
    }
    setBusy(true);
    setError(null);
    const deleted: string[] = [];
    const problems: string[] = [];
    for (const paper of pickedPapers) {
      try {
        await quizApi.deleteTemplate(paper.id);
        deleted.push(paper.id);
      } catch (err) {
        problems.push(`${paper.name}：${err instanceof Error ? err.message : '删除失败'}`);
      }
    }
    setBusy(false);
    if (problems.length) {
      setError(problems.join('；'));
      setPicked(new Set(pickedPapers.filter((paper) => !deleted.includes(paper.id)).map((paper) => paper.id)));
      setArmed(false);
      return;
    }
    await onDeleted();
  }

  return (
    <Modal onClose={onClose} title={`删除试卷 · 共 ${papers.length} 份`}>
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2 text-[12.5px] text-ink-muted">
          <span>
            已选 <span className="font-mono font-bold text-ink">{picked.size}</span> 份
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              className="focus-ring rounded px-1.5 py-0.5 text-ink-muted hover:text-ink"
              onClick={() => {
                setPicked(new Set(papers.map((paper) => paper.id)));
                setArmed(false);
              }}
            >
              全选
            </button>
            <span className="text-ink-faint">·</span>
            <button
              type="button"
              className="focus-ring rounded px-1.5 py-0.5 text-ink-muted hover:text-ink"
              onClick={() => {
                setPicked(new Set());
                setArmed(false);
              }}
            >
              清空
            </button>
          </div>
        </div>

        <ul className="max-h-[46vh] space-y-1 overflow-y-auto rounded-lg border border-line-soft p-1">
          {papers.map((paper) => {
            const checked = picked.has(paper.id);
            return (
              <li key={paper.id}>
                <label
                  className={cn(
                    'flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors',
                    checked ? 'bg-danger/10' : 'hover:bg-surface-raised',
                  )}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(paper.id)}
                    className="h-3.5 w-3.5 shrink-0 accent-danger"
                  />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{paper.name}</span>
                  <span className="shrink-0 font-mono text-[11.5px] text-ink-faint">
                    {paper.totalCount} 题 · {paper.durationMinutes} 分
                  </span>
                </label>
              </li>
            );
          })}
          {papers.length === 0 ? (
            <li className="px-2 py-6 text-center text-[12.5px] text-ink-faint">还没有试卷</li>
          ) : null}
        </ul>

        <p className="text-[12px] leading-relaxed text-ink-faint">
          只删除试卷本身，已考过的成绩记录不受影响。
        </p>

        {error && <ErrorNote message={error} onClose={() => setError(null)} />}

        <div className="flex justify-end gap-2 pt-1">
          <Button onClick={onClose}>取消</Button>
          <Button variant="danger" disabled={picked.size === 0 || busy} onClick={() => void handleDelete()}>
            {busy ? '删除中…' : armed ? `确认删除 ${picked.size} 份？` : `删除选中的 ${picked.size} 份`}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/** 试卷编辑器：抽题范围、题型分布、时长与乱序——模板即试卷，入口并入考试页 */
function PaperEditorModal({
  paper,
  banks,
  onClose,
  onSaved,
}: {
  paper: ExamTemplate | 'new';
  banks: Bank[];
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const isNew = paper === 'new';

  const [name, setName] = useState(isNew ? '' : paper.name);
  const [scopeBankId, setScopeBankId] = useState(isNew ? '' : paper.scopeBankId ?? '');
  const [scopeTagsText, setScopeTagsText] = useState(isNew ? '' : paper.scopeTags.join('、'));
  const [distribution, setDistribution] = useState<Record<string, number>>(
    isNew
      ? { single_choice: 10, multiple_choice: 5, true_false: 5, fill_blank: 0, subjective: 0 }
      : { ...paper.typeDistribution },
  );
  const [durationMinutes, setDurationMinutes] = useState(String(isNew ? 60 : paper.durationMinutes));
  const [shuffle, setShuffle] = useState(isNew ? true : paper.shuffle);
  const [isShared, setIsShared] = useState(isNew ? true : paper.isShared);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const total = TYPE_ORDER.reduce((sum, type) => sum + (distribution[type] || 0), 0);

  // 抽题范围内各题型实际有多少道：选了题库就按题库，否则按全部题库求和
  const available = useMemo(() => {
    const source: Record<string, number> = {};
    const scoped = scopeBankId ? banks.filter((bank) => bank.id === scopeBankId) : banks;
    for (const bank of scoped) {
      for (const [type, count] of Object.entries(bank.typeCounts ?? {})) {
        source[type] = (source[type] ?? 0) + count;
      }
    }
    return Object.fromEntries(TYPE_ORDER.map((type) => [type, source[type] ?? 0])) as Record<
      QuestionType,
      number
    >;
  }, [banks, scopeBankId]);

  const availableTotal = TYPE_ORDER.reduce((sum, type) => sum + available[type], 0);
  const shortages = TYPE_ORDER.filter((type) => (distribution[type] || 0) > available[type]);
  const tagLimited = scopeTagsText.trim().length > 0;

  async function handleSave() {
    if (!name.trim()) {
      setError('试卷名称不能为空');
      return;
    }
    if (total <= 0) {
      setError('至少需要一种题型且题量大于 0');
      return;
    }
    if (shortages.length) {
      setError(
        `抽题范围内题目不足：${shortages
          .map((type) => `${QUESTION_TYPE_LABEL[type]}需要 ${distribution[type] || 0} 道，仅有 ${available[type]} 道`)
          .join('；')}`,
      );
      return;
    }
    setSaving(true);
    try {
      const payload: TemplateInput = {
        name: name.trim(),
        scopeBankId: scopeBankId || null,
        scopeTags: scopeTagsText
          .split(/[,，、]/)
          .map((tag) => tag.trim())
          .filter(Boolean),
        typeDistribution: Object.fromEntries(
          TYPE_ORDER.filter((type) => (distribution[type] || 0) > 0).map((type) => [type, distribution[type] || 0]),
        ),
        totalCount: total,
        durationMinutes: Number(durationMinutes) || 60,
        shuffle,
        isShared,
      };
      if (isNew) {
        await quizApi.createTemplate(payload);
      } else {
        await quizApi.updateTemplate(paper.id, payload);
      }
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal onClose={onClose} title={isNew ? '新建试卷' : '编辑试卷'} wide>
      <div className="space-y-4">
        <Field label="试卷名称">
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="如：期末模拟卷" />
        </Field>

        <div className="flex gap-4">
          <div className="flex-1">
            <Field label="抽题范围 · 题库">
              <Select value={scopeBankId} onChange={(event) => setScopeBankId(event.target.value)}>
                <option value="">不限题库（全部题目 · {availableTotal} 题）</option>
                {banks.map((bank) => (
                  <option key={bank.id} value={bank.id}>
                    {bank.name}（{bank.questionCount ?? 0} 题）
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="flex-1">
            <Field label="限定标签" hint="选填，命中任一标签即纳入">
              <Input
                value={scopeTagsText}
                onChange={(event) => setScopeTagsText(event.target.value)}
                placeholder="用「、」分隔"
              />
            </Field>
          </div>
        </div>

        <Field label="题型分布">
          <div className="grid grid-cols-5 gap-3">
            {TYPE_ORDER.map((type) => {
              const short = (distribution[type] || 0) > available[type];
              return (
                <label key={type} className="text-center">
                  <span className="mb-1.5 block text-[12px] text-ink-muted">
                    {QUESTION_TYPE_LABEL[type]}
                  </span>
                  <Input
                    type="number"
                    min={0}
                    className={cn('text-center', short && 'border-danger text-danger')}
                    value={distribution[type] || 0}
                    onChange={(event) =>
                      setDistribution({
                        ...distribution,
                        [type]: Math.max(0, Number(event.target.value) || 0),
                      })
                    }
                  />
                  <span
                    className={cn('mt-1 block font-mono text-[11px]', short ? 'text-danger' : 'text-ink-faint')}
                  >
                    可抽 {available[type]}
                  </span>
                </label>
              );
            })}
          </div>
        </Field>

        {shortages.length ? (
          <p className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-[12.5px] leading-relaxed text-danger-deep">
            {tagLimited ? '按当前标签筛选后可能更少：' : ''}
            {shortages
              .map((type) => `${QUESTION_TYPE_LABEL[type]}最多 ${available[type]} 道`)
              .join('，')}
            ，请调小对应题量或换个题库。
          </p>
        ) : tagLimited ? (
          <p className="text-[12px] text-ink-faint">标签筛选后实际可抽题量可能少于上面的数字。</p>
        ) : null}

        <div className="flex items-center justify-between rounded-lg border border-line bg-sunken px-4 py-3">
          <span className="text-[13px] text-ink-muted">
            总题量（自动汇总）· 范围内共 {availableTotal} 题
          </span>
          <span className="font-mono text-[15px] font-bold text-ink">{total} 题</span>
        </div>

        <div className="flex flex-wrap gap-4">
          <div className="w-40">
            <Field label="考试时长（分钟）">
              <Input
                type="number"
                min={1}
                value={durationMinutes}
                onChange={(event) => setDurationMinutes(event.target.value)}
              />
            </Field>
          </div>
          <div className="flex min-w-[180px] flex-1 items-center justify-between rounded-lg border border-line bg-sunken px-4 py-2.5">
            <div>
              <p className="text-[13px] text-ink">乱序出题</p>
              <p className="mt-0.5 text-xs text-ink-faint">打乱题目与选项顺序</p>
            </div>
            <Switch checked={shuffle} onChange={setShuffle} label="乱序出题" />
          </div>
          <div className="flex items-center justify-between rounded-lg border border-line bg-sunken px-4 py-2.5">
            <div>
              <p className="text-[13px] text-ink">共享试卷</p>
            </div>
            <Switch checked={isShared} onChange={setIsShared} label="共享试卷" />
          </div>
        </div>

        {error && <ErrorNote message={error} onClose={() => setError(null)} />}
        <div className="flex justify-end gap-2 pt-2">
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" disabled={saving} onClick={() => void handleSave()}>
            {saving ? '保存中…' : '保存'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <Portal>
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-canvas/80 p-6"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={cn(
          'max-h-[86vh] w-full overflow-y-auto rounded-lg border border-line bg-surface shadow-overlay',
          wide ? 'max-w-2xl' : 'max-w-md',
        )}
      >
        <header className="flex items-center justify-between border-b border-line-soft px-6 py-4">
          <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose}>
            关闭
          </Button>
        </header>
        <div className="p-6">{children}</div>
      </div>
    </div>
    </Portal>
  );
}

function ScoreCard({
  label,
  value,
  max,
  tone,
  hint,
}: {
  label: string;
  value: number;
  max: number;
  tone: 'info' | 'warning' | 'accent' | 'success' | 'danger';
  hint?: string;
}) {
  const toneClass = {
    info: 'text-info',
    warning: 'text-warning',
    accent: 'text-primary',
    success: 'text-success',
    danger: 'text-danger',
  }[tone];
  return (
    <div className="rounded-lg border border-line bg-surface px-5 py-4 shadow-paper">
      <p className="text-xs font-semibold text-ink-muted">{label}</p>
      <p className={cn('mt-1.5 text-2xl font-extrabold leading-none tracking-[-0.02em]', toneClass)}>
        {Number.isInteger(value) ? value : value.toFixed(1)}
        <span className="text-sm font-bold text-ink-faint"> / {Number.isInteger(max) ? max : max.toFixed(1)}</span>
      </p>
      {hint && <p className="mt-1.5 text-[11px] text-ink-faint">{hint}</p>}
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

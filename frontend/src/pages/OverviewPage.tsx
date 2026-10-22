import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/auth';
import {
  api,
  quizApi,
  type Bank,
  type ExamHistoryItem,
  type HistoryResult,
  type PracticeHistoryItem,
} from '@/lib/api';
import { Badge, Card, Panel, Spinner } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { EmptyState, ProgressBar, Skeleton, Stat, StatusDot } from '@/components/ui/Feedback';
import { ProgressRing } from '@/components/ui/Charts';
import {
  IconAward,
  IconArrow,
  IconFile,
  IconLibrary,
  IconPlay,
  IconSliders,
  IconTarget,
} from '@/components/ui/icons';
import { QUESTION_TYPE_LABEL, type QuestionType, type SettingsResponse } from '@/lib/types';
import { cn } from '@/lib/cn';

const STEPS = [
  { label: '配置模型接口', to: '/settings', note: '填 OpenAI 兼容的 Base URL 与 Key' },
  { label: '导入题目', to: '/import', note: '文档 / 网页 / 图片 / 链接' },
  { label: '开始刷题', to: '/practice', note: '无限练、按标签、模拟考试' },
];

function greeting(hour: number) {
  if (hour < 6) return '夜里好';
  if (hour < 11) return '早安';
  if (hour < 14) return '午安';
  if (hour < 18) return '下午好';
  return '晚上好';
}

interface Snapshot {
  banks: Bank[];
  questionTotal: number;
  wrongOpen: number;
  wrongMastered: number;
  history: HistoryResult;
}

const EMPTY_HISTORY: HistoryResult = { practice: [], exams: [] };

/** 后端时间有两种写法：会话是 `datetime('now')`（UTC 无时区），考试是带 +00:00 的 isoformat */
function parseWhen(value: string): Date {
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasZone ? value : `${value.replace(' ', 'T')}Z`);
}

function formatWhen(value: string): string {
  const date = parseWhen(value);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const time = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
  if (sameDay) return `今天 ${time}`;
  const month = date.getMonth() + 1;
  const day = date.getDate();
  return date.getFullYear() === now.getFullYear() ? `${month}月${day}日 ${time}` : `${date.getFullYear()}/${month}/${day}`;
}

function practiceScope(item: PracticeHistoryItem): string {
  const base = item.bankName ?? '全部题库';
  const type = item.filters?.type;
  const tag = item.filters?.tag;
  const order = item.order === 'sequential' ? '顺序' : '随机';
  if (type) return `${order} · ${base} · ${QUESTION_TYPE_LABEL[type as QuestionType] ?? type}`;
  if (tag) return `${order} · ${base} · ${tag}`;
  return `${order} · ${base}`;
}

const EXAM_STATUS: Record<string, { label: string; tone: 'info' | 'warning' | 'success' | 'neutral' }> = {
  ongoing: { label: '进行中', tone: 'warning' },
  grading: { label: '阅卷中', tone: 'warning' },
  submitted: { label: '已交卷', tone: 'info' },
  graded: { label: '已出分', tone: 'success' },
};

export function OverviewPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyTab, setHistoryTab] = useState<'practice' | 'exam'>('practice');
  const [picked, setPicked] = useState<string[]>([]);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;

    Promise.all([
      quizApi.listBanks().catch(() => ({ banks: [] as Bank[] })),
      quizApi.listWrongQuestions().catch(() => ({ items: [] })),
      // 不传 limit：记录要全量，不是「最近几条」
      quizApi.history().catch(() => EMPTY_HISTORY),
      api.getSettings().catch(() => null),
    ]).then(([bankResult, wrongResult, historyResult, settingsResult]) => {
      if (!alive) return;

      const banks = bankResult.banks ?? [];
      const items = wrongResult.items ?? [];

      setSnapshot({
        banks,
        questionTotal: banks.reduce((sum, bank) => sum + (bank.questionCount ?? 0), 0),
        wrongOpen: items.filter((item) => !item.mastered).length,
        wrongMastered: items.filter((item) => item.mastered).length,
        // 后端或 mock 可能只回空对象，缺字段时兜住，别让记录卡片把整页带崩
        history: {
          practice: historyResult?.practice ?? [],
          exams: historyResult?.exams ?? [],
        },
      });
      setSettings(settingsResult);
      setLoading(false);
    });

    return () => {
      alive = false;
    };
  }, []);

  const configured = settings?.settings.ai_api_key_configured === 'true';
  const now = new Date();
  const wrongOpen = snapshot?.wrongOpen ?? 0;
  const wrongMastered = snapshot?.wrongMastered ?? 0;
  const wrongTotal = wrongOpen + wrongMastered;

  const practiceRows = snapshot?.history.practice ?? [];
  const examRows = snapshot?.history.exams ?? [];
  const currentRows = historyTab === 'practice' ? practiceRows : examRows;
  const allPicked = currentRows.length > 0 && currentRows.every((row) => picked.includes(row.id));

  function switchHistoryTab(next: 'practice' | 'exam') {
    setHistoryTab(next);
    setPicked([]);
    setConfirmingClear(false);
    setHistoryError(null);
  }

  function togglePicked(id: string) {
    setConfirmingClear(false);
    setPicked((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]));
  }

  function toggleAllPicked() {
    setConfirmingClear(false);
    setPicked(allPicked ? [] : currentRows.map((row) => row.id));
  }

  /** 清除选中记录：第一次点变成确认，第二次真正删，删完重新拉全量记录 */
  async function clearPicked() {
    if (!picked.length || clearing) return;
    if (!confirmingClear) {
      setConfirmingClear(true);
      return;
    }
    setClearing(true);
    setHistoryError(null);
    try {
      const deleted = await quizApi.deleteHistory(
        historyTab === 'practice' ? { practice: picked, exams: [] } : { practice: [], exams: picked },
      );
      setPicked([]);
      setConfirmingClear(false);
      const refreshed = await quizApi.history().catch(() => EMPTY_HISTORY);
      setSnapshot((prev) =>
        prev
          ? {
              ...prev,
              history: { practice: refreshed.practice ?? [], exams: refreshed.exams ?? [] },
            }
          : prev,
      );
      if (!deleted.deleted.practice && !deleted.deleted.exams) {
        setHistoryError('没有记录被清除，可能刚刚已被删掉');
      }
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : '清除失败');
    } finally {
      setClearing(false);
    }
  }

  const masteryRate = wrongTotal ? Math.round((wrongMastered / wrongTotal) * 100) : 100;

  return (
    <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-12">
      {/* 主瓦：问候 + 错题攻克环 + 行动入口 */}
      <Card
        className="relative overflow-hidden p-5 sm:col-span-2 lg:col-span-8"
        style={{
          backgroundImage:
            'radial-gradient(560px 280px at 90% -12%, rgb(var(--primary-rgb) / 0.08), transparent 65%)',
        }}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-[22px] font-extrabold leading-tight tracking-[-0.01em] text-ink">
              {greeting(now.getHours())}，{user?.displayName ?? ''}
            </h1>
            <p className="mt-1 text-[13px] text-ink-muted">
              {user?.isAdmin ? '管理员' : '普通用户'} ·{' '}
              {now.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })}
            </p>
          </div>
          <Badge tone={configured ? 'success' : 'warning'}>
            <StatusDot tone={configured ? 'success' : 'warning'} pulse={!configured} />
            {configured ? '模型接口已就绪' : '模型接口待配置'}
          </Badge>
        </div>

        {loading ? (
          <div className="mt-6 space-y-3">
            <Skeleton className="h-24" />
          </div>
        ) : (
          <div className="mt-6 flex flex-wrap items-center gap-6">
            <ProgressRing value={masteryRate} size={96} thickness={7} caption="错题攻克" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-[26px] font-extrabold leading-none text-ink">{wrongOpen}</span>
                <span className="text-[13px] text-ink-muted">题待攻克</span>
                <span className="text-[12.5px] text-ink-faint">
                  · 已掌握 {wrongMastered} 题，共 {wrongTotal} 题进本
                </span>
              </div>
              <div className="mt-4 flex flex-wrap gap-2.5">
                <Button variant="primary" onClick={() => navigate('/practice')}>
                  <IconPlay className="h-4 w-4" />
                  继续刷题
                </Button>
                <Button variant="secondary" onClick={() => navigate('/exam')}>
                  <IconAward className="h-4 w-4" />
                  模拟考试
                </Button>
              </div>
            </div>
          </div>
        )}
      </Card>

      {/* 右侧统计栈 */}
      <div className="grid gap-4 sm:col-span-2 lg:col-span-4">
        {loading ? (
          <>
            <Skeleton className="h-[86px]" />
            <Skeleton className="h-[86px]" />
            <Skeleton className="h-[86px]" />
          </>
        ) : (
          <>
            <Stat
              label="题库"
              value={snapshot?.banks.length ?? 0}
              unit="个"
              tone="accent"
              icon={<IconLibrary className="h-5 w-5" />}
            />
            <Stat
              label="题目"
              value={snapshot?.questionTotal ?? 0}
              unit="题"
              tone="info"
              icon={<IconFile className="h-5 w-5" />}
            />
            <Stat
              label="错题待清"
              value={wrongOpen}
              unit="题"
              tone={wrongOpen ? 'warning' : 'success'}
              icon={<IconTarget className="h-5 w-5" />}
            />
          </>
        )}
      </div>

      {/* 错题本 */}
      <Panel
        title="错题本"
        className="sm:col-span-1 lg:col-span-3"
        action={
          <Link
            to="/practice"
            className="focus-ring inline-flex items-center gap-1 rounded text-[12.5px] text-ink-muted transition-colors hover:text-primary"
          >
            去重刷
            <IconArrow className="h-3.5 w-3.5" />
          </Link>
        }
      >
        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-8 w-20" />
            <Skeleton className="h-4 w-full" />
          </div>
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className="text-[26px] font-extrabold leading-none text-ink">{wrongOpen}</span>
              <span className="text-[12.5px] text-ink-muted">题待攻克</span>
            </div>
            <p className="mt-2 text-[12.5px] text-ink-faint">
              {wrongTotal ? `已掌握 ${wrongMastered} 题，连对 2 次自动移出` : '还没有错题，保持住'}
            </p>
            <ProgressBar
              value={masteryRate}
              tone={masteryRate >= 80 ? 'success' : 'warning'}
              className="mt-3"
            />
          </>
        )}
      </Panel>

      {/* 开始使用 */}
      <Panel title="开始使用" description="三步把题做完，顺序走即可" className="sm:col-span-1 lg:col-span-4">
        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : (
          <ol className="space-y-0">
            {STEPS.map((step, index) => (
              <li
                key={step.to}
                className={cn(
                  'flex items-center gap-3.5 py-3',
                  'border-line-soft [&:not(:last-child)]:border-b first:pt-0 last:pb-0',
                )}
              >
                <Link
                  to={step.to}
                  className="focus-ring group -mx-2 flex min-w-0 flex-1 items-center gap-3.5 rounded-md px-2 py-1 transition-colors duration-200 hover:bg-surface-raised"
                >
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md border border-line bg-sunken text-[13px] font-bold text-primary transition-colors duration-200 group-hover:border-primary/50 group-hover:bg-primary group-hover:text-on-primary">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13.5px] text-ink">{step.label}</span>
                    <span className="mt-0.5 block truncate text-[12px] text-ink-faint">
                      {step.note}
                    </span>
                  </span>
                  <span
                    aria-hidden="true"
                    className="shrink-0 text-ink-faint transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-primary"
                  >
                    →
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        )}
      </Panel>

      {/* 记录：刷题 / 考试切换，可多选清除，点开看答卷。
          用 lg:order-1 压到最后一行，让上面的「题库 / 模型接口」保持原来的三栏位置。 */}
      <Panel
        title="记录"
        className="sm:col-span-2 lg:order-1 lg:col-span-12"
        action={
          <div className="flex items-center gap-2">
            <span className="hidden text-[11.5px] text-ink-faint sm:inline">
              共 {currentRows.length} 条
            </span>
            <div className="flex h-7 items-center rounded-md border border-line bg-sunken p-0.5">
              {(
                [
                  ['practice', '刷题'],
                  ['exam', '考试'],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => switchHistoryTab(key)}
                  aria-pressed={historyTab === key}
                  className={cn(
                    'focus-ring h-6 rounded px-2.5 text-[11.5px] font-medium transition-colors',
                    historyTab === key ? 'bg-surface text-primary shadow-paper' : 'text-ink-faint hover:text-ink',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        }
      >
        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
          </div>
        ) : currentRows.length === 0 ? (
          <p className="py-6 text-center text-[12.5px] text-ink-faint">
            {historyTab === 'practice' ? '还没有刷题记录' : '还没有考试记录'}
          </p>
        ) : (
          <>
            <div className="mb-2 flex items-center justify-between gap-3 border-b border-line-soft pb-2">
              <label className="flex cursor-pointer items-center gap-2 text-[12.5px] text-ink-muted">
                <input
                  type="checkbox"
                  checked={allPicked}
                  onChange={toggleAllPicked}
                  className="h-3.5 w-3.5 shrink-0 accent-primary"
                />
                全选
              </label>
              <div className="flex items-center gap-2">
                {picked.length ? (
                  <span className="text-[12px] text-ink-faint">已选 {picked.length} 条</span>
                ) : null}
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-danger"
                  disabled={!picked.length || clearing}
                  onClick={() => void clearPicked()}
                >
                  {clearing ? '清除中…' : confirmingClear ? `确认清除 ${picked.length} 条？` : '清除选中'}
                </Button>
              </div>
            </div>

            {historyError ? (
              <p className="mb-2 break-anywhere text-[12px] text-danger-deep">{historyError}</p>
            ) : null}

            <ul className="max-h-[420px] divide-y divide-line-soft overflow-y-auto">
              {historyTab === 'practice'
                ? practiceRows.map((item) => {
                    const rate = item.answered ? Math.round((item.correct / item.answered) * 100) : 0;
                    return (
                      <li key={item.id} className="flex items-center gap-2.5 py-1.5 first:pt-0 last:pb-0">
                        <input
                          type="checkbox"
                          checked={picked.includes(item.id)}
                          onChange={() => togglePicked(item.id)}
                          className="h-3.5 w-3.5 shrink-0 accent-danger"
                        />
                        <Link
                          to={`/practice?session=${item.id}`}
                          className="focus-ring -mx-1 flex min-w-0 flex-1 items-center gap-3 rounded-md px-1 py-1 transition-colors hover:bg-surface-raised"
                        >
                          <IconPlay className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[13px] text-ink">{practiceScope(item)}</span>
                            <span className="mt-0.5 block text-[11.5px] text-ink-faint">
                              {formatWhen(item.startedAt)} · 答 {item.answered}/{item.total}
                              {item.finishedAt ? '' : ' · 未完成'}
                            </span>
                          </span>
                          <span
                            className={cn(
                              'shrink-0 font-mono text-[12.5px] font-bold',
                              rate >= 60 ? 'text-success-deep' : 'text-warning-deep',
                            )}
                          >
                            {rate}%
                          </span>
                          <IconArrow className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
                        </Link>
                      </li>
                    );
                  })
                : examRows.map((item: ExamHistoryItem) => {
                    const status = EXAM_STATUS[item.status] ?? { label: item.status, tone: 'neutral' as const };
                    const score = item.totalScore;
                    return (
                      <li key={item.id} className="flex items-center gap-2.5 py-1.5 first:pt-0 last:pb-0">
                        <input
                          type="checkbox"
                          checked={picked.includes(item.id)}
                          onChange={() => togglePicked(item.id)}
                          className="h-3.5 w-3.5 shrink-0 accent-danger"
                        />
                        <Link
                          to={`/exam?exam=${item.id}`}
                          className="focus-ring -mx-1 flex min-w-0 flex-1 items-center gap-3 rounded-md px-1 py-1 transition-colors hover:bg-surface-raised"
                        >
                          <IconAward className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[13px] text-ink">
                              {item.templateName ?? '考试'}
                            </span>
                            <span className="mt-0.5 block text-[11.5px] text-ink-faint">
                              {formatWhen(item.startedAt)} · {item.questionCount} 题
                            </span>
                          </span>
                          <Badge tone={status.tone}>{status.label}</Badge>
                          <span className="w-16 shrink-0 text-right font-mono text-[12.5px] font-bold text-ink">
                            {score == null ? '—' : Number.isInteger(score) ? score : score.toFixed(1)}
                            {item.maxScore ? (
                              <span className="text-[11px] font-normal text-ink-faint">/{item.maxScore}</span>
                            ) : null}
                          </span>
                          <IconArrow className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
                        </Link>
                      </li>
                    );
                  })}
            </ul>
          </>
        )}
      </Panel>

      {/* 题库 + 模型接口 */}
      <div className="grid gap-4 sm:col-span-2 lg:col-span-5">
        <Panel
          title="题库"
          action={
            <Link
              to="/bank"
              className="focus-ring inline-flex items-center gap-1 rounded text-[12.5px] text-ink-muted transition-colors hover:text-primary"
            >
              全部
              <IconArrow className="h-3.5 w-3.5" />
            </Link>
          }
        >
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-8" />
              <Skeleton className="h-8" />
            </div>
          ) : snapshot && snapshot.banks.length ? (
            <ul className="space-y-1">
              {snapshot.banks.slice(0, 5).map((bank) => (
                <li key={bank.id}>
                  <Link
                    to={`/bank?bank=${bank.id}`}
                    className="focus-ring flex items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors duration-200 hover:bg-surface-raised"
                  >
                    <IconLibrary className="h-4 w-4 shrink-0 text-ink-faint" />
                    <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{bank.name}</span>
                    <span className="shrink-0 font-mono text-[12px] text-ink-faint">
                      {bank.questionCount ?? 0}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="还没有题库"
              description="去导入页把题目收进来"
              icon={<IconLibrary className="h-6 w-6" />}
              action={
                <Button variant="primary" size="sm" onClick={() => navigate('/import')}>
                  去导入
                </Button>
              }
            />
          )}
        </Panel>

        <Panel
          title="模型接口"
          action={
            <Link
              to="/settings"
              className="focus-ring rounded text-[12.5px] text-ink-muted transition-colors hover:text-primary"
            >
              去设置
            </Link>
          }
        >
          <div className="flex flex-wrap items-center gap-2.5">
            <StatusDot tone={configured ? 'success' : 'warning'} pulse={!configured} />
            <span className="text-[13px] text-ink">{configured ? '已配置' : '尚未配置'}</span>
            {settings?.settings.ai_model ? (
              <Badge tone="info">
                <IconSliders className="h-3.5 w-3.5" />
                {settings.settings.ai_model}
              </Badge>
            ) : null}
          </div>
          <p className="mt-2.5 truncate font-mono text-[12px] text-ink-faint">
            {settings?.settings.ai_base_url || '未填写 Base URL'}
          </p>
        </Panel>
      </div>
    </div>
  );
}

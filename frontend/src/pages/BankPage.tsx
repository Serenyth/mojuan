import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PageTitle, useWideContent } from '@/components/AppShell';
import { Badge, Panel } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Field, Input, Select, Textarea } from '@/components/ui/Form';
import { Switch } from '@/components/ui/Switch';
import { Portal } from '@/components/ui/Portal';
import { IconCheck, IconEdit, IconEye, IconGrid, IconList, IconTrash } from '@/components/ui/icons';
import { cn } from '@/lib/cn';
import { QUESTION_TYPE_LABEL, type Option, type QuestionType } from '@/lib/types';
import {
  exportQuestions,
  quizApi,
  type Bank,
  type QuestionDetail,
  type QuestionInput,
  type QuestionsPage,
} from '@/lib/api';

/** 题库管理页：题库切换、检索、单题编辑、导出。 */

const PAGE_SIZE = 20;
const LAYOUT_KEY = 'mojuan:bank-layout';
const PAGER_KEY = 'mojuan:bank-pager';
const CHOICE_TYPES: QuestionType[] = ['single_choice', 'multiple_choice', 'true_false'];

const TYPE_TONE: Record<QuestionType, 'neutral' | 'accent' | 'success' | 'warning' | 'info' | 'violet'> = {
  single_choice: 'info',
  multiple_choice: 'accent',
  true_false: 'warning',
  fill_blank: 'neutral',
  subjective: 'violet',
};

type BankLayout = 'list' | 'grid';
/** pages = 翻页；infinite = 滚到底自动加载 */
type PagerMode = 'pages' | 'infinite';

function readPref<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const saved = localStorage.getItem(key);
    return allowed.includes(saved as T) ? (saved as T) : fallback;
  } catch {
    return fallback;
  }
}

function writePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 隐私模式等场景忽略 */
  }
}

function DifficultyDots({ level }: { level: number }) {
  return (
    <span className="flex gap-1">
      {Array.from({ length: 5 }).map((_, i) => (
        <span key={i} className={cn('h-1.5 w-1.5 rounded-full', i < level ? 'bg-warning' : 'bg-line-strong')} />
      ))}
    </span>
  );
}

/** 管理视图里把答案还原成人话：选择题带选项原文，其余按分隔符拼 */
function formatAnswer(question: QuestionDetail): string {
  const raw = question.answer;
  const list = Array.isArray(raw) ? raw.map(String) : raw == null ? [] : [String(raw)];
  if (question.options?.length) {
    const text = list
      .map((key) => {
        const option = question.options?.find((item) => item.key === key);
        return option ? `${option.key}. ${option.text}` : key;
      })
      .join('；');
    return text || '未给出';
  }
  return list.filter(Boolean).join('；') || '未给出';
}

/** 正确答案的 key 集合，供选项高光用 */
function answerKeySet(answer: unknown): Set<string> {
  if (Array.isArray(answer)) return new Set(answer.map(String));
  if (answer == null) return new Set();
  return new Set([String(answer)]);
}

export function BankPage() {
  const [searchParams] = useSearchParams();
  const [banks, setBanks] = useState<Bank[]>([]);
  const [selectedBankId, setSelectedBankId] = useState<string | null>(null);

  // items 是「当前已加载的题目」：翻页模式下一页一份，滚动模式下一页页追加
  const [items, setItems] = useState<QuestionDetail[]>([]);
  const [meta, setMeta] = useState<{ total: number; tags: string[]; typeCounts: Record<string, number> } | null>(
    null,
  );
  const [pageNo, setPageNo] = useState(1); // 翻页模式当前页 / 滚动模式已加载到第几页
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);
  const [exhausted, setExhausted] = useState(false);

  // 右上角搜索芯片带 ?q= 跳进来时，直接落成关键词过滤
  const [keywordInput, setKeywordInput] = useState(searchParams.get('q') ?? '');
  const [filters, setFilters] = useState({ type: '', tag: '', keyword: searchParams.get('q') ?? '' });

  const [editing, setEditing] = useState<QuestionDetail | 'new' | null>(null);
  const [bankEditing, setBankEditing] = useState<Bank | 'new' | null>(null);
  const [bankManagerOpen, setBankManagerOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [showAnswers, setShowAnswers] = useState(false);
  const [showOptions, setShowOptions] = useState(false);
  const [layout, setLayout] = useState<BankLayout>(() => readPref(LAYOUT_KEY, ['list', 'grid'], 'list'));
  const [pager, setPager] = useState<PagerMode>(() => readPref(PAGER_KEY, ['pages', 'infinite'], 'pages'));
  // 网格态把内容区放宽到 1600，多出来的宽度换成第四列
  useWideContent(layout === 'grid');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reqRef = useRef(0); // 自增请求号，挡住筛选快速切换时的旧响应
  const moreLock = useRef(false); // 追加请求串行闸门
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const loadBanks = useCallback(async () => {
    try {
      const result = await quizApi.listBanks();
      setBanks(result.banks);
      setSelectedBankId((current) => current ?? result.banks[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '题库加载失败');
    }
  }, []);

  // 关键词防抖：输入即发请求会打一堆，等手停 320ms 再查
  useEffect(() => {
    const timer = window.setTimeout(() => setFilters((prev) => ({ ...prev, keyword: keywordInput.trim() })), 320);
    return () => window.clearTimeout(timer);
  }, [keywordInput]);

  const fetchPage = useCallback(
    (page: number) =>
      quizApi.listQuestions(selectedBankId as string, {
        type: filters.type || undefined,
        tag: filters.tag || undefined,
        keyword: filters.keyword || undefined,
        page,
        pageSize: PAGE_SIZE,
      }),
    [selectedBankId, filters.type, filters.tag, filters.keyword],
  );

  /** 换第 n 页（或从筛选条件重来）：整批替换 */
  const loadPage = useCallback(
    async (n: number) => {
      if (!selectedBankId) {
        setItems([]);
        setMeta(null);
        setExhausted(true);
        return;
      }
      const rid = ++reqRef.current;
      moreLock.current = false;
      setLoading(true);
      setMoreError(null);
      try {
        const res = await fetchPage(n);
        if (rid !== reqRef.current) return;
        setItems(res.items);
        setMeta({ total: res.total, tags: res.tags, typeCounts: res.typeCounts });
        setPageNo(n);
        setExhausted(res.items.length === 0);
      } catch (err) {
        if (rid === reqRef.current) setError(err instanceof Error ? err.message : '题目加载失败');
      } finally {
        if (rid === reqRef.current) setLoading(false);
      }
    },
    [fetchPage, selectedBankId],
  );

  const hasMore = !!meta && !exhausted && items.length < meta.total;

  /** 滚动模式：往后再要一页，追加到尾巴 */
  const loadMore = useCallback(async () => {
    if (!selectedBankId || moreLock.current || loading) return;
    if (!hasMore) return;
    const rid = reqRef.current;
    moreLock.current = true;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const res = await fetchPage(pageNo + 1);
      if (rid !== reqRef.current) return; // 期间改了筛选，这一页作废
      setItems((prev) => [...prev, ...res.items]);
      setMeta({ total: res.total, tags: res.tags, typeCounts: res.typeCounts });
      setPageNo(pageNo + 1);
      if (res.items.length === 0) setExhausted(true);
    } catch (err) {
      if (rid === reqRef.current) setMoreError(err instanceof Error ? err.message : '加载失败');
    } finally {
      moreLock.current = false;
      setLoadingMore(false);
    }
  }, [fetchPage, hasMore, loading, pageNo, selectedBankId]);

  useEffect(() => {
    void loadBanks();
  }, [loadBanks]);

  // 换题库、换筛选条件都从第一页重来
  useEffect(() => {
    void loadPage(1);
  }, [loadPage]);

  // 滚动模式的触底探测：提前 360px 就要，滚到底再等就白屏了
  useEffect(() => {
    if (pager !== 'infinite') return;
    const node = sentinelRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMore();
      },
      { rootMargin: '360px 0px' },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [pager, loadMore]);

  useEffect(() => writePref(LAYOUT_KEY, layout), [layout]);
  useEffect(() => writePref(PAGER_KEY, pager), [pager]);

  /** 增删改之后重取，别把已加载的多页缩回一页 */
  const refreshList = useCallback(async () => {
    if (pager === 'infinite' && pageNo > 1) {
      const rid = ++reqRef.current;
      moreLock.current = false;
      setLoading(true);
      setMoreError(null);
      try {
        const pages: QuestionsPage[] = [];
        for (let n = 1; n <= pageNo; n += 1) pages.push(await fetchPage(n));
        if (rid !== reqRef.current) return;
        const last = pages[pages.length - 1];
        setItems(pages.flatMap((item) => item.items));
        setMeta({ total: last.total, tags: last.tags, typeCounts: last.typeCounts });
        setExhausted(false);
      } catch (err) {
        if (rid === reqRef.current) setError(err instanceof Error ? err.message : '题目加载失败');
      } finally {
        if (rid === reqRef.current) setLoading(false);
      }
      return;
    }
    await loadPage(pager === 'infinite' ? 1 : pageNo);
  }, [fetchPage, loadPage, pageNo, pager]);

  function changePager(next: PagerMode) {
    if (next === pager) return;
    setPager(next);
    window.scrollTo({ top: 0 });
    void loadPage(1);
  }

  async function gotoPage(n: number) {
    await loadPage(n);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  const selectedBank = banks.find((bank) => bank.id === selectedBankId) ?? null;
  const total = meta?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const typeSummary = meta
    ? (Object.keys(QUESTION_TYPE_LABEL) as QuestionType[])
        .filter((type) => meta.typeCounts[type])
        .map((type) => `${QUESTION_TYPE_LABEL[type]} ${meta.typeCounts[type]}`)
        .join(' · ')
    : '';

  const subtitle = selectedBank
    ? `${selectedBank.name}${meta ? ` · 共 ${total} 题` : ''}${typeSummary ? ` · ${typeSummary}` : ''}`
    : '选择题库后查看、编辑与导出题目';

  async function handleDeleteQuestion(id: string) {
    try {
      await quizApi.deleteQuestion(id);
      setPendingDelete(null);
      setNotice('题目已删除');
      await Promise.all([refreshList(), loadBanks()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    }
  }

  /** 批量删除完成后：被删掉的题库不能继续选中，选中变化会触发列表重取 */
  async function handleBanksDeleted(deletedIds: string[], problem?: string) {
    setBankManagerOpen(false);
    if (deletedIds.length) setNotice(`已删除 ${deletedIds.length} 个题库`);
    if (problem) setError(problem);
    if (selectedBankId && deletedIds.includes(selectedBankId)) setSelectedBankId(null);
    await loadBanks();
  }

  async function handleExport(format: 'csv' | 'json') {
    try {
      await exportQuestions({ bankId: selectedBankId ?? undefined, format });
      setNotice(`已导出 ${format.toUpperCase()}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '导出失败');
    }
  }

  return (
    <div>
      <PageTitle
        title="题库管理"
        subtitle={subtitle}
        action={
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            {selectedBank ? (
              <>
                <Button size="sm" variant="ghost" onClick={() => setBankEditing(selectedBank)}>
                  重命名
                </Button>
                <Button size="sm" variant="ghost" className="text-danger" onClick={() => setBankManagerOpen(true)}>
                  删除题库
                </Button>
                <Button size="sm" variant="ghost" onClick={() => void handleExport('csv')}>
                  导出 CSV
                </Button>
                <Button size="sm" variant="ghost" onClick={() => void handleExport('json')}>
                  导出 JSON
                </Button>
              </>
            ) : null}
            <Button
              size="sm"
              variant="primary"
              onClick={() => setEditing('new')}
              disabled={!selectedBankId}
            >
              新建题目
            </Button>
          </div>
        }
      />

      {error && <ErrorNote message={error} onClose={() => setError(null)} />}
      {notice && <NoticeNote message={notice} onClose={() => setNotice(null)} />}

      {/* 筛选条：吸顶、紧凑，一行放下，滚长列表也不丢上下文 */}
      <div className="sticky top-[60px] z-30 -mx-1 mb-4 rounded-xl border border-line bg-surface/90 px-2 py-1.5 shadow-paper backdrop-blur-xl">
        <div className="flex flex-wrap items-center gap-1.5">
          <div className="w-40 shrink-0">
            <Select
              value={selectedBankId ?? ''}
              onChange={(event) => {
                if (event.target.value === '__new__') {
                  setBankEditing('new');
                  return;
                }
                setSelectedBankId(event.target.value || null);
              }}
            >
              <option value="">选择题库</option>
              {banks.map((bank) => (
                <option key={bank.id} value={bank.id}>
                  {bank.name}（{bank.questionCount ?? 0}）
                </option>
              ))}
              <option value="__new__">＋ 新建题库</option>
            </Select>
          </div>
          <div className="w-32 shrink-0">
            <Select
              value={filters.type}
              onChange={(event) => setFilters({ ...filters, type: event.target.value })}
            >
              <option value="">全部题型</option>
              {(Object.keys(QUESTION_TYPE_LABEL) as QuestionType[]).map((type) => (
                <option key={type} value={type}>
                  {QUESTION_TYPE_LABEL[type]}
                </option>
              ))}
            </Select>
          </div>
          <div className="w-32 shrink-0">
            <Select
              value={filters.tag}
              onChange={(event) => setFilters({ ...filters, tag: event.target.value })}
            >
              <option value="">全部标签</option>
              {(meta?.tags ?? []).map((tag) => (
                <option key={tag} value={tag}>
                  {tag}
                </option>
              ))}
            </Select>
          </div>
          {/* Input 自带 w-full，宽度得由外层壳子给，不然会撑满一整行 */}
          <div className="min-w-[10rem] flex-1">
            <Input
              placeholder="搜索题干关键词"
              value={keywordInput}
              onChange={(event) => setKeywordInput(event.target.value)}
            />
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <ToggleChip active={showOptions} onClick={() => setShowOptions((v) => !v)}>
              <IconEye className="h-3.5 w-3.5" />
              选项
            </ToggleChip>
            <ToggleChip active={showAnswers} onClick={() => setShowAnswers((v) => !v)}>
              <IconCheck className="h-3.5 w-3.5" />
              答案
            </ToggleChip>
            <LayoutToggle value={layout} onChange={setLayout} />
            <PagerSwitch value={pager} onChange={changePager} />
          </div>
        </div>
      </div>

      {/* 题目：列表 / 网格；滚动模式下这里会一页页往后长 */}
      {items.length > 0 ? (
        <div
          className={cn(
            layout === 'grid'
              ? 'grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4'
              : 'space-y-3',
          )}
        >
          {items.map((question, index) => (
            <QuestionCard
              key={question.id}
              question={question}
              serial={pager === 'infinite' ? index + 1 : (pageNo - 1) * PAGE_SIZE + index + 1}
              layout={layout}
              showOptions={showOptions}
              showAnswers={showAnswers}
              pendingDelete={pendingDelete === question.id}
              onEdit={() => setEditing(question)}
              onRequestDelete={() => setPendingDelete(question.id)}
              onCancelDelete={() => setPendingDelete(null)}
              onConfirmDelete={() => void handleDeleteQuestion(question.id)}
            />
          ))}
        </div>
      ) : (
        <Panel>
          <p className="py-10 text-center text-[13px] text-ink-faint">
            {loading ? '加载中…' : selectedBankId ? '没有符合条件的题目' : '请先选择或新建题库'}
          </p>
        </Panel>
      )}

      {/* 触底哨兵：IntersectionObserver 一进来就要下一页 */}
      {pager === 'infinite' && hasMore ? <div ref={sentinelRef} className="h-8" /> : null}

      {items.length > 0 ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-surface/70 px-3 py-1.5 text-[12.5px] text-ink-muted">
          <span>
            {pager === 'infinite' ? (
              <>
                已加载 <span className="font-mono text-ink">{items.length}</span> / {total} 题
              </>
            ) : (
              <>
                共 <span className="font-mono text-ink">{total}</span> 题
              </>
            )}
          </span>

          <div className="flex flex-wrap items-center gap-2">
            {pager === 'pages' && totalPages > 1 ? (
              <div className="flex items-center gap-2">
                <Button size="sm" disabled={pageNo <= 1 || loading} onClick={() => void gotoPage(pageNo - 1)}>
                  上一页
                </Button>
                <span className="font-mono text-[11.5px]">
                  {pageNo} / {totalPages}
                </span>
                <Button
                  size="sm"
                  disabled={pageNo >= totalPages || loading}
                  onClick={() => void gotoPage(pageNo + 1)}
                >
                  下一页
                </Button>
              </div>
            ) : null}

            {pager === 'infinite' ? (
              <span className="text-[11.5px] text-ink-faint">
                {moreError ? (
                  <button type="button" className="focus-ring text-danger hover:underline" onClick={() => void loadMore()}>
                    加载失败，点此重试
                  </button>
                ) : loadingMore ? (
                  '加载中…'
                ) : hasMore ? (
                  '继续下滑加载更多'
                ) : (
                  '已全部加载'
                )}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}

      {bankManagerOpen && (
        <BankDeleteModal
          banks={banks}
          selectedBankId={selectedBankId}
          onClose={() => setBankManagerOpen(false)}
          onDeleted={handleBanksDeleted}
        />
      )}

      {editing && selectedBankId && (
        <QuestionEditorModal
          bankId={selectedBankId}
          question={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            setNotice(editing === 'new' ? '题目已创建' : '题目已更新');
            await Promise.all([refreshList(), loadBanks()]);
          }}
        />
      )}

      {bankEditing && (
        <BankEditorModal
          bank={bankEditing}
          onClose={() => setBankEditing(null)}
          onSaved={async () => {
            setBankEditing(null);
            await loadBanks();
          }}
        />
      )}
    </div>
  );
}

/* ---------- 题目卡片（列表 / 网格共用） ---------- */

function QuestionCard({
  question,
  serial,
  layout,
  showOptions,
  showAnswers,
  pendingDelete,
  onEdit,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  question: QuestionDetail;
  serial: number;
  layout: BankLayout;
  showOptions: boolean;
  showAnswers: boolean;
  pendingDelete: boolean;
  onEdit: () => void;
  onRequestDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}) {
  const grid = layout === 'grid';
  const answerKeys = answerKeySet(question.answer);
  const accepted = (question.acceptableAnswers ?? []).filter((group) => group.length);

  return (
    <article
      className={cn(
        'group flex flex-col rounded-xl border border-line bg-surface shadow-paper transition-all duration-150 hover:border-line-strong hover:shadow-lifted',
        grid ? 'p-3.5' : 'p-4',
      )}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <span className="font-mono text-[11px] text-ink-faint">#{String(serial).padStart(2, '0')}</span>
          <Badge tone={TYPE_TONE[question.type]}>{QUESTION_TYPE_LABEL[question.type]}</Badge>
          {question.tags.slice(0, grid ? 2 : 6).map((tag) => (
            <Badge key={tag}>{tag}</Badge>
          ))}
          {question.tags.length > (grid ? 2 : 6) ? (
            <span className="text-[11px] text-ink-faint">+{question.tags.length - (grid ? 2 : 6)}</span>
          ) : null}
          {question.confidence < 0.8 && <Badge tone="warning">存疑</Badge>}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            onClick={onEdit}
            aria-label="编辑题目"
            title="编辑"
            className="focus-ring grid h-7 w-7 place-items-center rounded-md text-ink-faint transition-colors hover:bg-surface-raised hover:text-ink"
          >
            <IconEdit className="h-4 w-4" />
          </button>
          {pendingDelete ? (
            <>
              <Button size="sm" variant="danger" onClick={onConfirmDelete}>
                删除
              </Button>
              <Button size="sm" variant="ghost" onClick={onCancelDelete}>
                取消
              </Button>
            </>
          ) : (
            <button
              type="button"
              onClick={onRequestDelete}
              aria-label="删除题目"
              title="删除"
              className="focus-ring grid h-7 w-7 place-items-center rounded-md text-ink-faint transition-colors hover:bg-danger/10 hover:text-danger"
            >
              <IconTrash className="h-4 w-4" />
            </button>
          )}
        </div>
      </header>

      <p
        className={cn(
          'mt-2.5 whitespace-pre-wrap break-anywhere text-ink',
          grid ? 'text-[13.5px] leading-relaxed' : 'text-[14.5px] font-medium leading-relaxed',
          !showAnswers && (grid ? 'line-clamp-4' : 'line-clamp-3'),
        )}
      >
        {question.content}
      </p>

      {showOptions && question.options?.length ? (
        <ul className="mt-2.5 space-y-1">
          {question.options.map((option) => {
            const correct = answerKeys.has(option.key);
            return (
              <li
                key={option.key}
                className={cn(
                  'flex items-start gap-2 rounded-md border px-2 py-1.5 text-[12.5px] leading-relaxed',
                  correct
                    ? 'border-success/40 bg-success/10 text-ink'
                    : 'border-line-soft bg-surface-raised/40 text-ink-muted',
                )}
              >
                <span
                  className={cn(
                    'mt-[1px] grid h-[18px] min-w-[18px] place-items-center rounded px-1 font-mono text-[10px] font-bold',
                    correct ? 'bg-success text-white' : 'bg-sunken text-ink-faint',
                  )}
                >
                  {option.key}
                </span>
                <span className="min-w-0 flex-1 break-anywhere">{option.text}</span>
                {correct ? <IconCheck className="mt-[2px] h-3.5 w-3.5 shrink-0 text-success" /> : null}
              </li>
            );
          })}
        </ul>
      ) : null}

      {showAnswers ? (
        <div className="mt-2.5 space-y-1 border-t border-line-soft pt-2.5 text-[12.5px] leading-relaxed">
          <p className="text-ink-muted">
            <span className="mr-1.5 text-[11px] font-bold tracking-wide text-ink-faint">答案</span>
            <span className="break-anywhere font-semibold text-ink">{formatAnswer(question)}</span>
          </p>
          {accepted.length > 0 ? (
            <p className="text-ink-muted">
              <span className="mr-1.5 text-[11px] font-bold tracking-wide text-ink-faint">等价</span>
              <span className="break-anywhere">
                {accepted.map((group) => group.join(' / ')).join('；')}
              </span>
            </p>
          ) : null}
          {question.explanation ? (
            <p className="text-ink-muted">
              <span className="mr-1.5 text-[11px] font-bold tracking-wide text-ink-faint">解析</span>
              <span className="break-anywhere">{question.explanation}</span>
            </p>
          ) : null}
        </div>
      ) : null}

      <footer className="mt-auto flex items-center gap-3 pt-2.5 text-[11px] text-ink-faint">
        <span className="flex items-center gap-1.5">
          难度
          <DifficultyDots level={question.difficulty} />
        </span>
        {question.explanation ? <span>含解析</span> : null}
        {!grid && question.source ? <span className="truncate">来源 {question.source}</span> : null}
      </footer>
    </article>
  );
}

/* ---------- 筛选条小控件 ---------- */

function ToggleChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'focus-ring inline-flex h-10 items-center gap-1 rounded-md border px-3 text-[12.5px] font-medium transition-colors',
        active
          ? 'border-primary/40 bg-primary/10 text-primary'
          : 'border-line bg-surface text-ink-muted hover:border-line-strong hover:text-ink',
      )}
    >
      {children}
    </button>
  );
}

function LayoutToggle({ value, onChange }: { value: BankLayout; onChange: (next: BankLayout) => void }) {
  const options: Array<[BankLayout, typeof IconList, string]> = [
    ['list', IconList, '列表'],
    ['grid', IconGrid, '网格'],
  ];
  return (
    <div className="flex h-10 items-center rounded-md border border-line bg-sunken p-0.5">
      {options.map(([key, Icon, label]) => (
        <button
          key={key}
          type="button"
          onClick={() => onChange(key)}
          aria-pressed={value === key}
          title={`${label}布局`}
          className={cn(
            'focus-ring grid h-8 w-8 place-items-center rounded transition-colors',
            value === key ? 'bg-surface text-primary shadow-paper' : 'text-ink-faint hover:text-ink',
          )}
        >
          <Icon className="h-4 w-4" />
        </button>
      ))}
    </div>
  );
}

/** 翻页 / 无限滚动二选一：长题库滚着看更顺，短题库翻页更省事 */
function PagerSwitch({ value, onChange }: { value: PagerMode; onChange: (next: PagerMode) => void }) {
  const options: Array<[PagerMode, string, string]> = [
    ['pages', '分页', '分页浏览'],
    ['infinite', '滚动', '滚到底自动加载'],
  ];
  return (
    <div className="flex h-10 items-center rounded-md border border-line bg-sunken p-0.5">
      {options.map(([key, label, title]) => (
        <button
          key={key}
          type="button"
          onClick={() => onChange(key)}
          aria-pressed={value === key}
          title={title}
          className={cn(
            'focus-ring h-8 rounded px-2.5 text-[12px] font-medium transition-colors',
            value === key ? 'bg-surface text-primary shadow-paper' : 'text-ink-faint hover:text-ink',
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/* ---------- 题库编辑弹窗 ---------- */

function BankEditorModal({
  bank,
  onClose,
  onSaved,
}: {
  bank: Bank | 'new';
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const isNew = bank === 'new';
  const [name, setName] = useState(isNew ? '' : bank.name);
  const [platform, setPlatform] = useState(isNew ? '' : bank.platform ?? '');
  const [description, setDescription] = useState(isNew ? '' : bank.description ?? '');
  const [isShared, setIsShared] = useState(isNew ? true : bank.isShared);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!name.trim()) {
      setError('题库名称不能为空');
      return;
    }
    setSaving(true);
    try {
      if (isNew) {
        await quizApi.createBank({ name: name.trim(), platform: platform || undefined, description: description || undefined, isShared });
      } else {
        await quizApi.updateBank(bank.id, { name: name.trim(), platform: platform || undefined, description: description || undefined, isShared });
      }
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal onClose={onClose} title={isNew ? '新建题库' : '题库设置'}>
      <div className="space-y-4">
        <Field label="名称">
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="如：计算机网络 · 期末复习" />
        </Field>
        <Field label="平台 / 来源">
          <Input value={platform} onChange={(event) => setPlatform(event.target.value)} placeholder="如：牛客、LeetCode、示例" />
        </Field>
        <Field label="描述">
          <Textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="选填" />
        </Field>
        <div className="flex items-center justify-between rounded-lg border border-line bg-sunken px-4 py-3">
          <div>
            <p className="text-[13px] text-ink">共享题库</p>
            <p className="mt-0.5 text-xs text-ink-faint">关闭后仅所有者与管理员可管理</p>
          </div>
          <Switch checked={isShared} onChange={setIsShared} label="共享题库" />
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

/* ---------- 题目编辑弹窗 ---------- */

function countBlanks(content: string): number {
  return Math.max((content.match(/_{2,}/g) ?? []).length, 1);
}

function QuestionEditorModal({
  bankId,
  question,
  onClose,
  onSaved,
}: {
  bankId: string;
  question: QuestionDetail | 'new';
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const isNew = question === 'new';
  const existing = isNew ? null : question;

  const [type, setType] = useState<QuestionType>(existing?.type ?? 'single_choice');
  const [content, setContent] = useState(existing?.content ?? '');
  const [options, setOptions] = useState(
    existing?.options ?? [
      { key: 'A', text: '' },
      { key: 'B', text: '' },
      { key: 'C', text: '' },
      { key: 'D', text: '' },
    ],
  );
  const [answerKeys, setAnswerKeys] = useState<string[]>(() => {
    if (!existing) return [];
    const answer = existing.answer;
    return Array.isArray(answer) ? answer.map(String) : [String(answer)];
  });
  const [fillAnswers, setFillAnswers] = useState<string[]>(() =>
    existing && Array.isArray(existing.answer) ? existing.answer.map(String) : [],
  );
  const [acceptableLines, setAcceptableLines] = useState<string[]>(() =>
    existing?.acceptableAnswers?.map((set) => set.join('、')) ?? [],
  );
  const [subjectivePoints, setSubjectivePoints] = useState<string>(() =>
    existing && Array.isArray(existing.answer) ? existing.answer.join('\n') : '',
  );
  const [explanation, setExplanation] = useState(existing?.explanation ?? '');
  const [tagsText, setTagsText] = useState((existing?.tags ?? []).join('、'));
  const [difficulty, setDifficulty] = useState(String(existing?.difficulty ?? 3));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const blanks = countBlanks(content);
  const isChoice = CHOICE_TYPES.includes(type);
  const isFill = type === 'fill_blank';
  const isSubjective = type === 'subjective';

  function setFillAnswer(index: number, value: string) {
    const next = [...fillAnswers];
    while (next.length < blanks) next.push('');
    next[index] = value;
    setFillAnswers(next);
  }

  function setAcceptable(index: number, value: string) {
    const next = [...acceptableLines];
    while (next.length < blanks) next.push('');
    next[index] = value;
    setAcceptableLines(next);
  }

  function handleTypeChange(next: QuestionType) {
    setType(next);
    setAnswerKeys([]);
    if (next === 'true_false') {
      setOptions([
        { key: 'T', text: '正确' },
        { key: 'F', text: '错误' },
      ]);
    } else if (options.length < 2 || options[0].key === 'T') {
      setOptions([
        { key: 'A', text: '' },
        { key: 'B', text: '' },
        { key: 'C', text: '' },
        { key: 'D', text: '' },
      ]);
    }
  }

  function validate(): string | null {
    if (!content.trim()) return '题干不能为空';
    if (isChoice) {
      if (options.filter((option) => option.text.trim()).length < 2) return '选择题至少需要两个有效选项';
      if (answerKeys.length === 0) return '请选择正确答案';
      if (type === 'single_choice' && answerKeys.length > 1) return '单选题只能有一个答案';
    }
    if (isFill && !fillAnswers.slice(0, blanks).some((text) => text.trim())) return '填空题至少填写一个空的答案';
    if (isSubjective && !subjectivePoints.trim()) return '主观题需要填写参考答案要点';
    return null;
  }

  async function handleSave() {
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    try {
      const tags = tagsText
        .split(/[,，、]/)
        .map((tag) => tag.trim())
        .filter(Boolean);

      let optionsValue: Option[] | null = null;
      let answerValue: string[] | string;
      let acceptableValue: string[][] | null = null;
      if (isChoice) {
        optionsValue = options.filter((option) => option.text.trim());
        answerValue = type === 'multiple_choice' ? answerKeys : answerKeys.slice(0, 1);
      } else if (isFill) {
        answerValue = fillAnswers.slice(0, blanks);
        const acceptable = acceptableLines
          .slice(0, blanks)
          .map((line) => line.split(/[,，、]/).map((text) => text.trim()).filter(Boolean));
        acceptableValue = acceptable.some((set) => set.length > 0) ? acceptable : null;
      } else {
        answerValue = subjectivePoints.split('\n').map((line) => line.trim()).filter(Boolean);
      }

      if (existing) {
        const patch: Partial<QuestionInput> = {
          content: content.trim(),
          options: optionsValue,
          answer: answerValue,
          acceptableAnswers: acceptableValue,
          explanation: explanation.trim() || null,
          tags,
          difficulty: Number(difficulty),
        };
        await quizApi.updateQuestion(existing.id, patch);
      } else {
        const payload: QuestionInput = {
          bankId,
          type,
          content: content.trim(),
          options: optionsValue,
          answer: answerValue,
          acceptableAnswers: acceptableValue,
          explanation: explanation.trim() || null,
          tags,
          difficulty: Number(difficulty),
        };
        await quizApi.createQuestion(payload);
      }
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal onClose={onClose} title={isNew ? '新建题目' : '编辑题目'} wide>
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          {isNew ? (
            <Select className="w-36" value={type} onChange={(event) => handleTypeChange(event.target.value as QuestionType)}>
              {(Object.keys(QUESTION_TYPE_LABEL) as QuestionType[]).map((item) => (
                <option key={item} value={item}>
                  {QUESTION_TYPE_LABEL[item]}
                </option>
              ))}
            </Select>
          ) : (
            <Badge tone={TYPE_TONE[type]}>{QUESTION_TYPE_LABEL[type]}</Badge>
          )}
          <span className="text-xs text-ink-faint">
            {isChoice ? '选项点击左侧字母可设为答案' : isFill ? '用 ____ 表示空格' : ''}
          </span>
        </div>

        <Field label="题干" hint="支持 Markdown 原文；填空用 ____ 标记空位">
          <Textarea rows={4} value={content} onChange={(event) => setContent(event.target.value)} />
        </Field>

        {isChoice && (
          <Field label="选项">
            <div className="space-y-2">
              {options.map((option, index) => (
                <div key={option.key} className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      setAnswerKeys(
                        type === 'multiple_choice'
                          ? answerKeys.includes(option.key)
                            ? answerKeys.filter((key) => key !== option.key)
                            : [...answerKeys, option.key]
                          : [option.key],
                      )
                    }
                    className={cn(
                      'focus-ring grid h-9 w-9 shrink-0 place-items-center border font-mono text-xs font-bold transition-colors',
                      type === 'multiple_choice' ? 'rounded-lg' : 'rounded-full',
                      answerKeys.includes(option.key)
                        ? 'border-primary bg-primary text-on-primary'
                        : 'border-line-strong text-ink-faint hover:border-primary/60 hover:text-primary',
                    )}
                  >
                    {option.key}
                  </button>
                  <Input
                    value={option.text}
                    disabled={type === 'true_false'}
                    onChange={(event) =>
                      setOptions(options.map((item, i) => (i === index ? { ...item, text: event.target.value } : item)))
                    }
                    placeholder={`选项 ${option.key}`}
                  />
                  {type !== 'true_false' && options.length > 2 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-primary"
                      onClick={() => setOptions(options.filter((_, i) => i !== index))}
                    >
                      删
                    </Button>
                  )}
                </div>
              ))}
              {type !== 'true_false' && (
                <Button
                  size="sm"
                  onClick={() =>
                    setOptions([...options, { key: String.fromCharCode(65 + options.length), text: '' }])
                  }
                >
                  添加选项
                </Button>
              )}
            </div>
          </Field>
        )}

        {isFill && (
          <Field label="填空答案" hint={`检测到 ${blanks} 个空；可接受答案用「、」分隔，留空则只认标准答案`}>
            <div className="space-y-2">
              {Array.from({ length: blanks }).map((_, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="w-12 shrink-0 text-right font-mono text-xs text-ink-faint">
                    第 {i + 1} 空
                  </span>
                  <Input
                    value={fillAnswers[i] ?? ''}
                    onChange={(event) => setFillAnswer(i, event.target.value)}
                    placeholder="标准答案"
                  />
                  <Input
                    value={acceptableLines[i] ?? ''}
                    onChange={(event) => setAcceptable(i, event.target.value)}
                    placeholder="可接受答案（选填）"
                  />
                </div>
              ))}
            </div>
          </Field>
        )}

        {isSubjective && (
          <Field label="参考答案要点" hint="每行一个要点，用于阅卷时对照">
            <Textarea rows={4} value={subjectivePoints} onChange={(event) => setSubjectivePoints(event.target.value)} />
          </Field>
        )}

        <Field label="解析">
          <Textarea rows={2} value={explanation} onChange={(event) => setExplanation(event.target.value)} placeholder="选填" />
        </Field>

        <div className="flex gap-4">
          <div className="flex-1">
            <Field label="标签">
              <Input value={tagsText} onChange={(event) => setTagsText(event.target.value)} placeholder="用「、」分隔" />
            </Field>
          </div>
          <div className="w-32">
            <Field label="难度">
              <Select value={difficulty} onChange={(event) => setDifficulty(event.target.value)}>
                {[1, 2, 3, 4, 5].map((level) => (
                  <option key={level} value={level}>
                    {'★'.repeat(level)}
                  </option>
                ))}
              </Select>
            </Field>
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

/* ---------- 基础组件 ---------- */

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

/* ---------- 题库批量删除 ---------- */

function BankDeleteModal({
  banks,
  selectedBankId,
  onClose,
  onDeleted,
}: {
  banks: Bank[];
  selectedBankId: string | null;
  onClose: () => void;
  onDeleted: (deletedIds: string[], problem?: string) => void | Promise<void>;
}) {
  const [picked, setPicked] = useState<Set<string>>(() => new Set(selectedBankId ? [selectedBankId] : []));
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pickedBanks = banks.filter((bank) => picked.has(bank.id));
  const questionTotal = pickedBanks.reduce((sum, bank) => sum + (bank.questionCount ?? 0), 0);

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
    for (const bank of pickedBanks) {
      try {
        await quizApi.deleteBank(bank.id);
        deleted.push(bank.id);
      } catch (err) {
        problems.push(`${bank.name}：${err instanceof Error ? err.message : '删除失败'}`);
      }
    }
    setBusy(false);
    if (problems.length) {
      setError(problems.join('；'));
      setPicked(new Set(pickedBanks.filter((bank) => !deleted.includes(bank.id)).map((bank) => bank.id)));
      setArmed(false);
      return;
    }
    await onDeleted(deleted);
  }

  return (
    <Modal onClose={onClose} title={`删除题库 · 共 ${banks.length} 个`}>
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2 text-[12.5px] text-ink-muted">
          <span>
            已选 <span className="font-mono font-bold text-ink">{picked.size}</span> 个 · 含{' '}
            <span className="font-mono font-bold text-ink">{questionTotal}</span> 题
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              className="focus-ring rounded px-1.5 py-0.5 text-ink-muted hover:text-ink"
              onClick={() => {
                setPicked(new Set(banks.map((bank) => bank.id)));
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
          {banks.map((bank) => {
            const checked = picked.has(bank.id);
            return (
              <li key={bank.id}>
                <label
                  className={cn(
                    'flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors',
                    checked ? 'bg-danger/10' : 'hover:bg-surface-raised',
                  )}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(bank.id)}
                    className="h-3.5 w-3.5 shrink-0 accent-danger"
                  />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{bank.name}</span>
                  <span className="shrink-0 font-mono text-[11.5px] text-ink-faint">
                    {bank.questionCount ?? 0} 题
                  </span>
                </label>
              </li>
            );
          })}
          {banks.length === 0 ? (
            <li className="px-2 py-6 text-center text-[12.5px] text-ink-faint">还没有题库</li>
          ) : null}
        </ul>

        <p className="text-[12px] leading-relaxed text-ink-faint">
          删除题库会连同其中全部题目一起移除，不可恢复。
        </p>

        {error && <ErrorNote message={error} onClose={() => setError(null)} />}

        <div className="flex justify-end gap-2 pt-1">
          <Button onClick={onClose}>取消</Button>
          <Button
            variant="danger"
            disabled={picked.size === 0 || busy}
            onClick={() => void handleDelete()}
          >
            {busy ? '删除中…' : armed ? `确认删除 ${picked.size} 个？` : `删除选中的 ${picked.size} 个`}
          </Button>
        </div>
      </div>
    </Modal>
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

function NoticeNote({ message, onClose }: { message: string; onClose: () => void }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-4 rounded-md border border-success/30 bg-success/10 px-4 py-3 text-[13px] text-success-deep">
      <span className="break-anywhere">{message}</span>
      <button type="button" onClick={onClose} className="focus-ring shrink-0 text-ink-faint hover:text-ink">
        ✕
      </button>
    </div>
  );
}

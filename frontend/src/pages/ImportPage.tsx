import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { PageTitle } from '@/components/AppShell';
import { Badge, Panel } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input, Select, Textarea } from '@/components/ui/Form';
import { EmptyState, SectionLabel, Skeleton, StatusDot } from '@/components/ui/Feedback';
import { ScriptWall } from '@/components/ScriptWall';
import { ImportFormatDialog } from '@/components/ImportFormatDialog';
import { IconBraces, IconClock, IconInbox, IconPlus, IconTrash, IconUpload } from '@/components/ui/icons';
import {
  api,
  chatApi,
  importApi,
  isApiError,
  quizApi,
  type Bank,
  type CandidateQuestion,
  type ChatAction,
  type ExtractDirectAction,
  type ChatEvent,
  type Conversation,
  type ConversationMessage,
  type ImportSource,
} from '@/lib/api';
import { QUESTION_TYPE_LABEL, type ExtractionScript } from '@/lib/types';
import { cn } from '@/lib/cn';

type Mode = 'ai' | 'script';
type SourceKind = ImportSource['type'];

interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  /** step 是 agent 的工具轨迹：紧凑一行，不当成对话气泡 */
  kind?: 'text' | 'step';
  ok?: boolean;
  /** 这条消息之前的思考：思考链对用户可见，过程透明 */
  thought?: string;
  /** 耗时（毫秒）：step 是本步（模型+工具），text 是整轮总耗时 */
  ms?: number;
}

/** 欢迎语不进会话记录：它只是占位，不是对话内容 */
const WELCOME: Message = {
  id: 'm0',
  role: 'assistant',
  text: '把材料或链接交给我，怎么拆我自己想办法——抓网页、写代码、造工具都行。结果会先在这里等你过目。',
};

/** 候选题在客户端挂个 key：候选没有 id，删除与勾选都要能定位 */
type Candidate = CandidateQuestion & { key: string };

const ACCEPT = '.pdf,.doc,.docx,.md,.markdown,.txt,.csv,.json,.html,.htm,.png,.jpg,.jpeg,.webp';

const KIND_LABEL: Record<SourceKind, string> = {
  document: '文档',
  image: '图片',
  url: '链接',
  text: '文本',
};

/** 左栏材料项的元信息行：字数 / 网页图片数 / 状态 */
function sourceMetaLine(source: ImportSource) {
  const imageCount = Number(source.meta?.imageCount ?? 0);
  const bits: string[] = [KIND_LABEL[source.type]];
  if (source.charCount) bits.push(`${source.charCount} 字`);
  if (imageCount) bits.push(`${imageCount} 张图 · 视觉读取`);
  if (!source.charCount && !imageCount && source.type !== 'image') bits.push('暂无内容');
  bits.push(source.status === 'ready' ? '就绪' : source.status);
  return bits.join(' · ');
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function errorText(error: unknown): string {
  return isApiError(error) ? error.detail : '网络异常，请稍后重试';
}

/** 流式响应非 2xx 时的错误信息（可能是未开流的 422，body 是 JSON） */
async function streamError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === 'string') return payload.detail;
  } catch {
    // 不是 JSON：退回到状态码
  }
  return `请求失败（${response.status}）`;
}

/** 毫秒 → 「12.3s」；不到 10ms 显示 <0.1s，别出现 0.0s */
function seconds(ms: number | null | undefined): string {
  if (ms == null) return '';
  const value = ms / 1000;
  return value < 0.1 ? '<0.1s' : `${value.toFixed(1)}s`;
}

/** 会话列表的相对时间。服务端存的是 UTC（SQLite datetime('now')） */
function relativeTime(iso: string): string {
  const then = new Date(`${iso.replace(' ', 'T')}Z`).getTime();
  if (Number.isNaN(then)) return '';
  const diff = Date.now() - then;
  if (diff < 60_000) return '刚刚';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`;
  const date = new Date(then);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: Array<{ value: T; label: string; note?: string; disabled?: boolean }>;
  onChange: (next: T) => void;
}) {
  return (
    <div className="grid gap-1 rounded-lg border border-line-soft bg-sunken p-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          disabled={option.disabled}
          onClick={() => onChange(option.value)}
          aria-pressed={value === option.value}
          className={cn(
            'focus-ring rounded-md px-2.5 py-1.5 text-left transition-all duration-200 ease-out',
            'disabled:cursor-not-allowed disabled:opacity-50',
            value === option.value
              ? 'bg-surface-raised text-ink shadow-paper'
              : 'text-ink-muted hover:bg-surface/60 hover:text-ink',
          )}
        >
          <span className="block text-[13px]">{option.label}</span>
          {option.note ? (
            <span className="mt-0.5 block text-[11.5px] leading-snug text-ink-faint">
              {option.note}
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

function Checkbox({ checked, onToggle, label }: { checked: boolean; onToggle: () => void; label: string }) {
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
          <path d="M2.5 6.5 4.8 8.8 9.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : null}
    </button>
  );
}

function CandidateCard({
  candidate,
  checked,
  onToggle,
  onRemove,
}: {
  candidate: Candidate;
  checked: boolean;
  onToggle: () => void;
  onRemove: () => void;
}) {
  const answerText = Array.isArray(candidate.answer) ? candidate.answer.filter(Boolean).join('、') : String(candidate.answer ?? '');
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
            {candidate.tags.length ? <span className="min-w-0">{candidate.tags.map((tag) => `#${tag}`).join(' ')}</span> : null}
          </div>

          {candidate.explanation ? (
            <p className="mt-1.5 break-anywhere border-l-2 border-line-strong pl-2 text-[12px] leading-relaxed text-ink-faint">
              {candidate.explanation}
            </p>
          ) : null}
        </div>

        <button
          type="button"
          aria-label="移除这道题"
          onClick={onRemove}
          className="focus-ring shrink-0 rounded px-1 text-ink-faint transition-colors hover:text-danger"
        >
          ×
        </button>
      </div>
    </li>
  );
}

export function ImportPage() {
  const [mode, setMode] = useState<Mode>('ai');
  const [sources, setSources] = useState<ImportSource[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loadingSources, setLoadingSources] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [savingKind, setSavingKind] = useState<'url' | 'text' | null>(null);
  const [dragging, setDragging] = useState(false);
  const [urlDraft, setUrlDraft] = useState('');
  const [textDraft, setTextDraft] = useState('');
  const [addingUrl, setAddingUrl] = useState(false);
  const [addingText, setAddingText] = useState(false);
  const [draft, setDraft] = useState('');
  const [instruction, setInstruction] = useState('');
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [showConversations, setShowConversations] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(true);
  const [banks, setBanks] = useState<Bank[]>([]);
  const [bankId, setBankId] = useState('');
  const [creatingBank, setCreatingBank] = useState(false);
  const [newBankName, setNewBankName] = useState('');
  const [savingBank, setSavingBank] = useState(false);
  const [aiReady, setAiReady] = useState<boolean | null>(null);
  const [chatting, setChatting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  /** 把某脚本「加入对话」后，AI 能看到并改写 / 跑沙盒调试它 */
  const [scriptId, setScriptId] = useState<string | null>(null);
  const [attachedScriptName, setAttachedScriptName] = useState('');
  /** 数据格式 / 导入提示词弹窗 */
  const [showFormat, setShowFormat] = useState(false);
  /** 右栏空 / 失败时的可展开详情 */
  const [extractInfo, setExtractInfo] = useState<
    { kind: 'empty' | 'error'; message: string; detail?: string } | null
  >(null);

  const fileInput = useRef<HTMLInputElement | null>(null);
  const feedRef = useRef<HTMLDivElement | null>(null);
  const keySeq = useRef(0);
  // 会话 id 的同步镜像：异步流程（流式收尾、系统气泡落库）里要立刻拿到
  // 当前会话，不能等 setState 重渲染
  const conversationIdRef = useRef<string | null>(null);

  function useConversation(id: string | null) {
    conversationIdRef.current = id;
    setConversationId(id);
  }

  useEffect(() => {
    quizApi
      .listBanks()
      .then((result) => setBanks(result.banks ?? []))
      .catch(() => setBanks([]));
    importApi
      .listSources()
      .then((result) => {
        const list = result.sources ?? [];
        setSources(list);
        setSelected(new Set(list.map((item) => item.id)));
      })
      .catch(() => setSources([]))
      .finally(() => setLoadingSources(false));
    api.getSettings()
      .then((result) =>
        setAiReady(Boolean(result.settings.ai_base_url) && result.settings.ai_api_key_configured === 'true'),
      )
      .catch(() => setAiReady(null));
    // 会话记录：刷新后接着最近一轮聊，不丢历史
    void loadConversationList();
  }, []);

  async function loadConversationList() {
    try {
      const result = await chatApi.list();
      setConversations(result.conversations ?? []);
      const latest = result.conversations?.[0];
      // 用 ref 判当前会话：runChat 的 finally 里调到这里时，conversationId 状态
      // 可能还是旧闭包里的 null，会误判成「没有会话」而重新 open 并覆盖刚铺好的轨迹
      if (latest && !conversationIdRef.current) await openConversation(latest.id);
    } catch {
      setConversations([]);
    } finally {
      setLoadingConversations(false);
    }
  }

  /** 打开一轮会话：消息从库里还原（轨迹、思考、耗时都在） */
  async function openConversation(id: string) {
    try {
      const result = await chatApi.get(id);
      const restored: Message[] = result.messages.map((item, index) => ({
        id: `h${index}-${item.id}`,
        role: item.role === 'user' ? 'user' : 'assistant',
        text: item.text,
        kind: item.kind === 'step' ? 'step' : 'text',
        ok: item.ok ?? undefined,
        thought: item.thought || undefined,
        ms: item.ms ?? undefined,
      }));
      setMessages(restored.length ? restored : [WELCOME]);
      useConversation(id);
      setShowConversations(false);
    } catch (error) {
      pushMessage('assistant', `读取会话失败：${errorText(error)}`);
    }
  }

  /** 开一轮新会话：消息清回欢迎语，id 置空，发首条消息时再建 */
  function startNewConversation() {
    useConversation(null);
    setMessages([WELCOME]);
    setShowConversations(false);
  }

  async function deleteConversation(id: string) {
    try {
      await chatApi.remove(id);
      setConversations((prev) => prev.filter((item) => item.id !== id));
      if (conversationId === id) startNewConversation();
    } catch (error) {
      pushMessage('assistant', `删除会话失败：${errorText(error)}`);
    }
  }

  useEffect(() => {
    const feed = feedRef.current;
    if (feed) feed.scrollTop = feed.scrollHeight;
  }, [messages.length]);

  const selectedIds = sources.filter((item) => selected.has(item.id)).map((item) => item.id);
  const totalChars = sources.reduce((sum, source) => sum + source.charCount, 0);
  const suspectCount = candidates.filter((item) => item.suspect || item.issues.length).length;
  const bankName = banks.find((bank) => bank.id === bankId)?.name ?? '';

  // 流程：提交材料 → AI 对话决定怎么拆 → AI 提取 → 选择题库（可新建）→ 确认入库。
  // 提取不依赖题库，所以这里只要求有材料。
  const canExtract = selectedIds.length > 0 && !extracting && !chatting;

  function pushMessage(role: Message['role'], text: string, thought?: string, ms?: number) {
    keySeq.current += 1;
    setMessages((prev) => [...prev, { id: `m${keySeq.current}`, role, text, thought, ms }]);
  }

  /** 系统气泡（提取结果、失败原因等）：进界面的同时落进会话记录 */
  async function pushNote(text: string) {
    pushMessage('assistant', text);
    const conv = conversationIdRef.current;
    if (conv) {
      try {
        await chatApi.append(conv, { role: 'assistant', text });
      } catch {
        // 落库失败不阻塞对话：界面已经显示了
      }
    }
  }

  /** agent 的工具轨迹：一步一行，让用户看见它到底干了什么 */
  function pushStep(note: string, ok: boolean, thought?: string, ms?: number) {
    keySeq.current += 1;
    setMessages((prev) => [
      ...prev,
      { id: `m${keySeq.current}`, role: 'assistant', text: note, kind: 'step', ok, thought, ms },
    ]);
  }

  function appendSource(source: ImportSource) {
    setSources((prev) => [source, ...prev.filter((item) => item.id !== source.id)]);
    setSelected((prev) => new Set(prev).add(source.id));
  }

  async function addFiles(files: FileList | null) {
    if (!files || !files.length) return;
    setUploading(true);
    for (const file of Array.from(files)) {
      try {
        const result = await importApi.uploadSource(file);
        appendSource(result.source);
      } catch (error) {
        pushMessage('assistant', `「${file.name}」导入失败：${errorText(error)}`);
      }
    }
    setUploading(false);
  }

  async function addUrl() {
    const value = urlDraft.trim();
    if (!value) return;
    setSavingKind('url');
    try {
      const result = await importApi.addUrlSource(value);
      appendSource(result.source);
      setUrlDraft('');
      setAddingUrl(false);
    } catch (error) {
      pushMessage('assistant', `链接抓取失败：${errorText(error)}`);
    } finally {
      setSavingKind(null);
    }
  }

  async function addText() {
    const value = textDraft.trim();
    if (!value) return;
    setSavingKind('text');
    try {
      const result = await importApi.addTextSource(value);
      appendSource(result.source);
      setTextDraft('');
      setAddingText(false);
    } catch (error) {
      pushMessage('assistant', `原文导入失败：${errorText(error)}`);
    } finally {
      setSavingKind(null);
    }
  }

  async function removeSource(source: ImportSource) {
    setSources((prev) => prev.filter((item) => item.id !== source.id));
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(source.id);
      return next;
    });
    try {
      await importApi.deleteSource(source.id);
    } catch (error) {
      pushMessage('assistant', `「${source.name}」删除失败：${errorText(error)}`);
    }
  }

  function toggleSource(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  /** 提取后就地新建题库：创建完直接选中，省得回题库页再回来 */
  async function createBank() {
    const name = newBankName.trim();
    if (!name) return;
    setSavingBank(true);
    try {
      const result = await quizApi.createBank({ name, isShared: true });
      setBanks((prev) => [...prev, result.bank]);
      setBankId(result.bank.id);
      setCreatingBank(false);
      setNewBankName('');
    } catch (error) {
      pushMessage('assistant', `新建题库失败：${errorText(error)}`);
    } finally {
      setSavingBank(false);
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    void addFiles(event.dataTransfer.files);
  }

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || chatting || extracting) return;
    pushMessage('user', text);
    setInstruction(text);
    setDraft('');
    // 新会话先建记录（标题取首条消息），流式端点接着往里写
    let target = conversationIdRef.current;
    if (!target) {
      try {
        const created = await chatApi.create(text.slice(0, 24));
        target = created.conversation.id;
        useConversation(target);
      } catch (error) {
        await pushNote(`建立会话失败：${errorText(error)}`);
        return;
      }
    }
    await runChat(text, target);
  }

  /** 把用户的话送给导入助手 agent（流式）：每完成一步就铺进行案，
   *  思维链随跑随长，不用整轮憋完才看见；每步带耗时，收尾带总耗时 */
  async function runChat(text: string, conversation: string) {
    setChatting(true);
    try {
      const response = await chatApi.stream({
        message: text,
        conversationId: conversation,
        sourceIds: selectedIds,
        scriptId: scriptId || null,
      });
      if (!response.ok || !response.body) {
        await pushNote(`对话失败：${await streamError(response)}`);
        return;
      }
      const action = await consumeStream(response.body);
      if (!action) return;
      if (action.type === 'extract_direct') {
        await runChatAction(action);
      } else if (action.type === 'confirm') {
        await pushNote('⏸ 已暂停，等待你确认。直接回复即可继续。');
      }
    } catch (error) {
      await pushNote(`对话失败：${errorText(error)}`);
    } finally {
      setChatting(false);
      void loadConversationList();
    }
  }

  /** 读 SSE 流：step 事件实时铺轨迹（含当步耗时），reply 收尾并返回动作 */
  async function consumeStream(body: ReadableStream<Uint8Array>): Promise<ChatAction | null> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let action: ChatAction | null = null;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let split = buffer.indexOf('\n\n');
      while (split >= 0) {
        const raw = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);
        split = buffer.indexOf('\n\n');
        const data = raw
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim())
          .join('');
        if (!data) continue;
        let event: ChatEvent;
        try {
          event = JSON.parse(data) as ChatEvent;
        } catch {
          continue;
        }
        if (event.type === 'step') {
          pushStep(event.note, event.ok, event.thought, event.ms);
        } else if (event.type === 'reply') {
          pushMessage('assistant', event.reply, event.thought, event.ms_total);
          action = event.action;
        } else if (event.type === 'error') {
          await pushNote(event.message);
        }
      }
    }
    return action;
  }

  /** 对话收尾后的提取动作（仅 extract_direct） */
  async function runChatAction(action: ExtractDirectAction) {
    if (action.jobId) {
      // agent 已经跑过 extract_questions：直接取候选，不再打一次提取
      try {
        const job = await importApi.getJob(action.jobId);
        await applyExtraction(job.questions, job.job.stats);
        if (job.questions.length === 0) {
          const skipped = (job.job.stats?.skipped as string[] | undefined) ?? [];
          setExtractInfo({
            kind: 'empty',
            message: '没有提取到题目',
            detail: skipped.length
              ? `被跳过的材料：${skipped.join('；')}`
              : '模型可能认为材料里没有题目，或材料内容为空。换更清晰的材料，或在对话里补充说明。',
          });
        }
      } catch (error) {
        setExtractInfo({ kind: 'error', message: '读取提取结果失败', detail: errorText(error) });
        await pushNote(`读取提取结果失败：${errorText(error)}`);
      }
      return;
    }

    // 没有 jobId（模型没走工具直接收尾）：对话里给的链接由服务端抓取后
    // 当场作为材料。已在左侧的同名链接复用 id 不重复创建。
    const ids = [...action.sourceIds];
    for (const url of action.urls ?? []) {
      const existing = sources.find((item) => item.name === url);
      if (existing) {
        ids.push(existing.id);
        continue;
      }
      try {
        const created = await importApi.addUrlSource(url);
        appendSource(created.source);
        ids.push(created.source.id);
      } catch (error) {
        await pushNote(`链接抓取失败：${errorText(error)}`);
      }
    }
    await runExtraction(ids, action.instruction);
  }

  /** 把一次提取的候选铺进右栏：重复题默认不勾，存疑题默认勾上逼着用户看一眼 */
  async function applyExtraction(questions: CandidateQuestion[], stats?: Record<string, unknown>) {
    keySeq.current += 1;
    const next: Candidate[] = questions.map((question) => ({
      ...question,
      key: `c${keySeq.current}-${question.fingerprint}-${Math.random().toString(36).slice(2, 6)}`,
    }));
    setCandidates(next);
    setChecked(new Set(next.filter((item) => !item.duplicate).map((item) => item.key)));
    if (next.length > 0) setExtractInfo(null);
    const skipped = (stats?.skipped as string[] | undefined) ?? [];
    if (!skipped.length) return;
    await pushNote(`有材料被跳过：${skipped.join('；')}`);
  }

  /** 真正的提取动作：对话触发与「开始提取」按钮都走这里 */
  async function runExtraction(sourceIds: string[], instructionText: string) {
    if (!sourceIds.length || extracting) return;
    setExtracting(true);
    try {
      const result = await importApi.extractDirect({ sourceIds, instruction: instructionText });
      await applyExtraction(result.questions, result.job.stats);
      if (result.questions.length === 0) {
        const skipped = (result.job.stats?.skipped as string[] | undefined) ?? [];
        setExtractInfo({
          kind: 'empty',
          message: '没有提取到题目',
          detail: skipped.length
            ? `被跳过的材料：${skipped.join('；')}`
            : '模型可能认为材料里没有题目，或材料内容为空。换更清晰的材料，或在对话里补充说明。',
        });
        await pushNote('没有提取到题目，可在对话里补充要求后重试。');
      } else {
        setExtractInfo(null);
        await pushNote(`提取到 ${result.questions.length} 题。逐条过目后点右下角确认入库。`);
      }
    } catch (error) {
      setExtractInfo({ kind: 'error', message: '提取失败', detail: errorText(error) });
      await pushNote(`提取失败：${errorText(error)}`);
    } finally {
      setExtracting(false);
    }
  }

  /** 「开始提取」按钮：跳过对话，按当前补充要求直接跑 */
  async function startExtract() {
    if (!canExtract) return;
    const note = draft.trim();
    const activeInstruction = note || instruction;
    if (note) {
      pushMessage('user', note);
      setInstruction(note);
      setDraft('');
    }
    await runExtraction(selectedIds, activeInstruction);
  }

  function toggleCandidate(key: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function confirmImport() {
    const chosen = candidates.filter((item) => checked.has(item.key));
    if (!chosen.length || !bankId) return;
    setConfirming(true);
    try {
      const payload: CandidateQuestion[] = chosen.map((item) => {
        const { key: _drop, ...question } = item;
        return question;
      });
      const result = await importApi.confirmImport({ bankId, questions: payload });
      await pushNote(`已导入 ${result.created} 题到「${bankName}」。`);
      setCandidates([]);
      setChecked(new Set());
    } catch (error) {
      await pushNote(`入库失败：${errorText(error)}`);
    } finally {
      setConfirming(false);
    }
  }

  /** 把脚本「加入对话」：切到 AI 模式并把脚本代码注入对话上下文，
   *  之后可以直接让 AI 改代码 / 加功能 / 挑材料跑沙盒看结果 */
  function attachScript(script: ExtractionScript) {
    setScriptId(script.id);
    setAttachedScriptName(script.name);
    setMode('ai');
    pushMessage(
      'assistant',
      `已把脚本「${script.name}」加入对话。你可以直接让我改代码、加功能，或挑材料跑一下看结果。`,
    );
  }

  /** 取消脚本上下文：AI 回到普通导入助手，不再看到脚本代码 */
  function detachScript() {
    setScriptId(null);
    setAttachedScriptName('');
    pushMessage('assistant', '已退出脚本调试。');
  }

  return (
    <div className="flex flex-col gap-4 lg:h-[calc(100vh-196px)]">
      <PageTitle
        title="导入"
        subtitle={mode === 'ai' ? '文档 · 网页 · 图片 · 链接，交给 AI 自己决定怎么拆' : '复用脚本批量提取，或把脚本交 AI 改代码 / 调试'}
        action={
          aiReady === false ? (
            <Link to="/settings">
              <Badge tone="warning">
                <StatusDot tone="warning" pulse />
                模型接口未配置 · 去设置
              </Badge>
            </Link>
          ) : aiReady ? (
            <Badge tone="success">
              <StatusDot tone="success" />
              直接提取就绪
            </Badge>
          ) : null
        }
      />

      {/* grid-cols-1 = minmax(0,1fr)：窄屏单列也必须能收缩到容器宽，
          否则数据源里的长链接（truncate 的 nowrap  Min-content = 整条 URL）会把隐式 auto 轨道顶宽 */}
      <div
        className={cn(
          'grid min-h-0 flex-1 grid-cols-1 gap-4',
          mode === 'ai'
            ? 'lg:grid-cols-[264px_minmax(0,1fr)_340px]'
            : 'lg:grid-cols-[264px_minmax(0,1fr)]',
        )}
      >
        {/* ── 左：数据源 ───────────────────────────── */}
        <Panel
          flush
          title="数据源"
          className="flex min-h-0 flex-col"
          action={
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              disabled={uploading}
              className="focus-ring rounded text-[12.5px] text-primary transition-colors hover:text-primary-hover disabled:opacity-50"
            >
              {uploading ? '上传中' : '添加'}
            </button>
          }
        >
          <input
            ref={fileInput}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            onChange={(event) => {
              void addFiles(event.target.files);
              event.target.value = '';
            }}
          />

          <div className="flex min-h-0 flex-1 flex-col gap-3 p-3">
            <div
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={cn(
                'rounded-lg border border-dashed px-4 py-7 text-center transition-all duration-200 ease-out',
                dragging
                  ? 'border-primary bg-primary/10 shadow-glow'
                  : 'border-line-strong hover:border-primary/50 hover:bg-surface-raised/60',
              )}
            >
              <IconUpload className="mx-auto h-6 w-6 text-ink-faint" />
              <p className="mt-2.5 text-[12.5px] text-ink-muted">拖到此处</p>
              <p className="mt-1 font-mono text-[11px] leading-relaxed text-ink-faint">
                pdf docx md txt csv html
                <br />
                png jpg webp
              </p>
            </div>

            {loadingSources ? (
              <div className="space-y-1.5">
                <Skeleton className="h-11" />
                <Skeleton className="h-11" />
              </div>
            ) : sources.length ? (
              <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto">
                {sources.map((source) => {
                  const isSelected = selected.has(source.id);
                  return (
                    <li key={source.id}>
                      <button
                        type="button"
                        onClick={() => toggleSource(source.id)}
                        aria-pressed={isSelected}
                        title={source.preview || source.name}
                        className={cn(
                          'focus-ring group flex w-full items-center gap-2 rounded-md border px-2.5 py-2 text-left transition-colors',
                          isSelected
                            ? 'border-line bg-surface-raised/40'
                            : 'border-line-soft opacity-60 hover:opacity-90',
                        )}
                      >
                        <Checkbox checked={isSelected} onToggle={() => toggleSource(source.id)} label="提取这份材料" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[12.5px] text-ink">{source.name}</p>
                          <p className="text-[11px] text-ink-faint">{sourceMetaLine(source)}</p>
                        </div>
                        <span
                          role="button"
                          tabIndex={0}
                          aria-label={`移除 ${source.name}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            void removeSource(source);
                          }}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault();
                              event.stopPropagation();
                              void removeSource(source);
                            }
                          }}
                          className="focus-ring shrink-0 rounded px-1 text-ink-faint opacity-0 transition-opacity hover:text-danger group-hover:opacity-100"
                        >
                          ×
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-[12px] leading-relaxed text-ink-faint">
                还没有材料。可以拖文件、粘贴链接，或直接贴一段题目原文。
              </p>
            )}

            <div className="space-y-2 border-t border-line-soft pt-3">
              <div className="flex gap-1.5">
                <Button
                  variant="secondary"
                  size="sm"
                  className="flex-1"
                  onClick={() => {
                    setAddingUrl((prev) => !prev);
                    setAddingText(false);
                  }}
                >
                  {addingUrl ? '收起' : '链接'}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  className="flex-1"
                  onClick={() => {
                    setAddingText((prev) => !prev);
                    setAddingUrl(false);
                  }}
                >
                  {addingText ? '收起' : '原文'}
                </Button>
              </div>

              {addingUrl ? (
                <div className="flex gap-1.5">
                  <Input
                    value={urlDraft}
                    onChange={(event) => setUrlDraft(event.target.value)}
                    placeholder="https://"
                    autoFocus
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault();
                        void addUrl();
                      }
                    }}
                  />
                  <Button variant="primary" size="sm" onClick={() => void addUrl()} loading={savingKind === 'url'}>
                    加入
                  </Button>
                </div>
              ) : null}

              {addingText ? (
                <div className="space-y-1.5">
                  <Textarea
                    value={textDraft}
                    onChange={(event) => setTextDraft(event.target.value)}
                    placeholder="把题目原文贴在这里"
                    className="min-h-[92px] resize-y"
                  />
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => void addText()}
                    disabled={!textDraft.trim()}
                    loading={savingKind === 'text'}
                    className="w-full"
                  >
                    加入 · {textDraft.length} 字
                  </Button>
                </div>
              ) : null}

              <span className="block text-[11.5px] text-ink-faint">
                共 {sources.length} 份材料 · 已选 {selectedIds.length} 份
                {totalChars ? ` · ${totalChars} 字` : ''}
              </span>
            </div>

            <div className="space-y-2 border-t border-line-soft pt-3">
              <SectionLabel>提取方式</SectionLabel>
              <Segmented
                value={mode}
                onChange={setMode}
                options={[
                  { value: 'ai', label: 'AI 提取', note: '让 AI 决定怎么拆 · 也可直接提取' },
                  { value: 'script', label: '脚本提取', note: '复用脚本批量提 · 可交 AI 调试' },
                ]}
              />
            </div>
          </div>
        </Panel>

        {mode === 'ai' ? (
        <>
        {/* ── 中：AI 对话 ───────────────────────────── */}
        <Panel
          flush
          title="AI 对话"
          description="它自己决定怎么抓，也可点开始提取"
          className="flex min-h-0 flex-col"
          action={
            <div className="relative flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowFormat(true)}
                className="focus-ring flex items-center gap-1 rounded-md px-2 py-1 text-[12.5px] text-ink-muted transition-colors hover:text-ink"
                title="数据格式与导入提示词"
              >
                <IconBraces className="h-4 w-4" />
                数据格式
              </button>
              <button
                type="button"
                onClick={() => setShowConversations((value) => !value)}
                className="focus-ring flex items-center gap-1 rounded-md px-2 py-1 text-[12.5px] text-ink-muted transition-colors hover:text-ink"
                aria-pressed={showConversations}
              >
                <IconClock className="h-4 w-4" />
                会话{conversationId ? '' : ''}
              </button>
              {showConversations ? (
                <>
                  <div
                    className="fixed inset-0 z-10"
                    onClick={() => setShowConversations(false)}
                    aria-hidden="true"
                  />
                  <div className="absolute right-0 top-[calc(100%+8px)] z-20 w-72 rounded-lg border border-line-soft bg-surface p-2 shadow-paper">
                    <div className="flex items-center justify-between px-1 pb-2">
                      <span className="text-[12.5px] font-medium text-ink">会话记录</span>
                      <button
                        type="button"
                        onClick={startNewConversation}
                        className="focus-ring flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] text-primary hover:text-primary-hover"
                      >
                        <IconPlus className="h-3.5 w-3.5" />
                        新会话
                      </button>
                    </div>
                    <div className="max-h-72 space-y-1 overflow-y-auto">
                      {loadingConversations ? (
                        <p className="px-1 py-3 text-center text-[12px] text-ink-faint">加载中…</p>
                      ) : conversations.length === 0 ? (
                        <p className="px-1 py-3 text-center text-[12px] text-ink-faint">还没有会话</p>
                      ) : (
                        conversations.map((conv) => (
                          <div
                            key={conv.id}
                            className={cn(
                              'group flex items-center gap-2 rounded-md px-2 py-1.5 transition-colors',
                              conv.id === conversationId ? 'bg-surface-raised' : 'hover:bg-surface-raised/60',
                            )}
                          >
                            <button
                              type="button"
                              onClick={() => void openConversation(conv.id)}
                              className="focus-ring min-w-0 flex-1 text-left"
                            >
                              <p className="truncate text-[12.5px] text-ink">{conv.title}</p>
                              <p className="truncate text-[11px] text-ink-faint">
                                {relativeTime(conv.updatedAt)} · {conv.messageCount} 条
                                {conv.lastMessage ? ` · ${conv.lastMessage}` : ''}
                              </p>
                            </button>
                            <button
                              type="button"
                              onClick={() => void deleteConversation(conv.id)}
                              aria-label="删除会话"
                              className="focus-ring shrink-0 rounded p-1 text-ink-faint opacity-0 transition-opacity hover:text-danger group-hover:opacity-100"
                            >
                              <IconTrash className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </>
              ) : null}
              <Badge tone="neutral">
                <StatusDot tone="neutral" />
                已选 {selectedIds.length} 份
              </Badge>
            </div>
          }
        >
          <div ref={feedRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
            {messages.map((message, index) =>
              message.kind === 'step' ? (
                <div
                  key={message.id}
                  style={{ animationDelay: `${Math.min(index, 6) * 40}ms` }}
                  className="animate-rise"
                >
                  {message.thought ? (
                    <p className="mb-1 ml-7 break-anywhere border-l-2 border-line-soft pl-2 text-[11.5px] leading-relaxed text-ink-faint">
                      {message.thought}
                    </p>
                  ) : null}
                  <div className="flex items-center gap-1.5 rounded-md border border-line-soft bg-surface-raised/70 px-2.5 py-1.5 text-[12px] text-ink-muted">
                    <StatusDot tone={message.ok ? 'success' : 'danger'} />
                    <span className="min-w-0 flex-1 break-anywhere">{message.text}</span>
                    {message.ms != null ? (
                      <span className="shrink-0 tabular-nums text-ink-faint">{seconds(message.ms)}</span>
                    ) : null}
                  </div>
                </div>
              ) : (
                <div
                  key={message.id}
                  style={{ animationDelay: `${Math.min(index, 6) * 40}ms` }}
                  className={cn(
                    'animate-rise flex gap-2.5',
                    message.role === 'user' ? 'flex-row-reverse' : undefined,
                  )}
                >
                  <span
                    className={cn(
                      'mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md font-display text-[12px]',
                      message.role === 'user'
                        ? 'bg-primary text-on-primary'
                        : 'bg-primary/10 text-primary',
                    )}
                  >
                    {message.role === 'user' ? '我' : '墨'}
                  </span>
                  <div className="max-w-[76%] space-y-1">
                    {message.thought ? (
                      <p className="break-anywhere border-l-2 border-line-soft pl-2 text-[11.5px] leading-relaxed text-ink-faint">
                        {message.thought}
                      </p>
                    ) : null}
                    <p
                      className={cn(
                        'rounded-lg px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap',
                        message.role === 'user'
                          ? 'bg-primary text-on-primary'
                          : 'border border-line bg-surface-raised text-ink shadow-paper',
                      )}
                    >
                      {message.text}
                    </p>
                    {message.ms != null && message.role === 'assistant' ? (
                      <p className="pl-3 text-[11px] tabular-nums text-ink-faint">
                        本轮 {seconds(message.ms)}
                      </p>
                    ) : null}
                  </div>
                </div>
              ),
            )}
            {chatting && !extracting ? (
              <div className="flex items-center gap-2 text-[12.5px] text-ink-faint">
                <StatusDot tone="info" pulse />
                墨卷正在想怎么拆……
              </div>
            ) : null}
            {extracting ? (
              <div className="flex items-center gap-2 text-[12.5px] text-ink-faint">
                <StatusDot tone="warning" pulse />
                模型正在读材料，通常要几十秒……
              </div>
            ) : null}
          </div>

          <div className="border-t border-line-soft p-3">
            {scriptId ? (
              <div className="mb-2 flex items-center gap-2 rounded-md border border-primary/30 bg-primary/10 px-2.5 py-1.5 text-[12px] text-primary">
                <span className="min-w-0 flex-1 truncate">
                  调试脚本：{attachedScriptName}
                </span>
                <button
                  type="button"
                  onClick={detachScript}
                  className="focus-ring shrink-0 rounded px-1 text-primary/70 transition-colors hover:text-primary"
                  aria-label="退出脚本调试"
                >
                  ×
                </button>
              </div>
            ) : null}
            <form onSubmit={send} className="flex items-end gap-2">
              <Textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) send();
                }}
                placeholder="发链接，或说怎么拆，⌘/Ctrl + Enter 发送"
                className="min-h-[52px] flex-1 resize-none"
              />
              <Button type="submit" variant="primary" size="md" disabled={!draft.trim() || chatting || extracting}>
                发送
              </Button>
            </form>

            <div className="mt-2.5 flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                loading={extracting}
                disabled={!canExtract}
                onClick={() => void startExtract()}
                title={canExtract ? undefined : '需要至少一份材料'}
              >
                开始提取
              </Button>
              <span className="text-[11.5px] text-ink-faint">
                {canExtract ? '材料已就位' : '需要至少一份材料'}
              </span>
            </div>
          </div>
        </Panel>

        {/* ── 右：提取结果 · 待审核 ─────────────────── */}
        <Panel
          flush
          title="提取结果 · 待审核"
          className="flex min-h-0 flex-col"
          action={<Badge tone="neutral">{candidates.length} 题</Badge>}
        >
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="grid grid-cols-3 gap-px border-b border-line-soft bg-line-soft">
              {[
                { label: '已提取', value: candidates.length, tone: 'info' as const },
                { label: '待确认', value: checked.size, tone: 'warning' as const },
                { label: '存疑', value: suspectCount, tone: 'violet' as const },
              ].map((cell) => (
                <div key={cell.label} className="bg-surface px-3 py-2.5">
                  <div className="flex items-center gap-1.5">
                    <StatusDot tone={cell.tone} />
                    <span className="text-[11px] text-ink-faint">{cell.label}</span>
                  </div>
                  <span className="mt-1 block text-[18px] font-extrabold leading-none text-ink">
                    {cell.value}
                  </span>
                </div>
              ))}
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {candidates.length ? (
                <ul className="space-y-2">
                  {candidates.map((candidate) => (
                    <CandidateCard
                      key={candidate.key}
                      candidate={candidate}
                      checked={checked.has(candidate.key)}
                      onToggle={() => toggleCandidate(candidate.key)}
                      onRemove={() => {
                        setCandidates((prev) => prev.filter((item) => item.key !== candidate.key));
                        setChecked((prev) => {
                          const next = new Set(prev);
                          next.delete(candidate.key);
                          return next;
                        });
                      }}
                    />
                  ))}
                </ul>
              ) : extractInfo ? (
                <div className="space-y-3">
                  <div
                    className={cn(
                      'rounded-md border p-3',
                      extractInfo.kind === 'error'
                        ? 'border-danger/30 bg-danger/10'
                        : 'border-warning/30 bg-warning/10',
                    )}
                  >
                    <p
                      className={cn(
                        'flex items-center gap-1.5 text-[13px] font-medium',
                        extractInfo.kind === 'error' ? 'text-danger-deep' : 'text-warning-deep',
                      )}
                    >
                      <StatusDot tone={extractInfo.kind === 'error' ? 'danger' : 'warning'} />
                      {extractInfo.message}
                    </p>
                    {extractInfo.detail ? (
                      extractInfo.kind === 'error' ? (
                        <pre className="mt-1.5 max-h-56 overflow-auto whitespace-pre-wrap break-anywhere rounded bg-surface-raised p-2 font-mono text-[11.5px] leading-relaxed text-ink-muted">
                          {extractInfo.detail}
                        </pre>
                      ) : (
                        <details className="mt-1.5">
                          <summary className="cursor-pointer select-none text-[12px] text-ink-muted">
                            查看详情
                          </summary>
                          <pre className="mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap break-anywhere rounded bg-surface-raised p-2 font-mono text-[11.5px] leading-relaxed text-ink-muted">
                            {extractInfo.detail}
                          </pre>
                        </details>
                      )
                    ) : null}
                  </div>
                  <EmptyState
                    title="尚无提取结果"
                    description="修正问题后可重试；也可以换个材料，或在对话里补充要求。"
                    icon={<IconInbox className="h-7 w-7" />}
                  />
                </div>
              ) : (
                <EmptyState
                  title="尚无提取结果"
                  description="材料送进模型后，题目会先落在这里等你逐条过目，确认后才会进题库。"
                  icon={<IconInbox className="h-7 w-7" />}
                />
              )}
            </div>

            {candidates.length ? (
              <div className="space-y-2 border-t border-line-soft px-3 pt-3">
                <SectionLabel>导入到题库</SectionLabel>
                {creatingBank ? (
                  <div className="flex gap-1.5">
                    <Input
                      value={newBankName}
                      onChange={(event) => setNewBankName(event.target.value)}
                      placeholder="新题库名称"
                      autoFocus
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.preventDefault();
                          void createBank();
                        }
                      }}
                    />
                    <Button
                      variant="primary"
                      size="sm"
                      loading={savingBank}
                      disabled={!newBankName.trim()}
                      onClick={() => void createBank()}
                    >
                      创建
                    </Button>
                  </div>
                ) : (
                  <Select
                    value={bankId}
                    onChange={(event) => {
                      if (event.target.value === '__new__') {
                        setCreatingBank(true);
                        return;
                      }
                      setBankId(event.target.value);
                    }}
                  >
                    <option value="">选择题库</option>
                    {banks.map((bank) => (
                      <option key={bank.id} value={bank.id}>
                        {bank.name}
                      </option>
                    ))}
                    <option value="__new__">＋ 新建题库</option>
                  </Select>
                )}
              </div>
            ) : null}

            <div className="flex items-center gap-2 border-t border-line-soft p-3">
              <Button
                variant="primary"
                size="sm"
                loading={confirming}
                disabled={!checked.size || !bankId}
                onClick={() => void confirmImport()}
                title={bankId ? undefined : '先选择或新建目标题库'}
                className="flex-1"
              >
                确认导入{checked.size ? ` ${checked.size} 题` : ''}
              </Button>
              <Button variant="ghost" size="sm" disabled title="阶段 4 开放">
                导出
              </Button>
            </div>
          </div>
        </Panel>
        </>
        ) : (
          <ScriptWall onAttach={attachScript} />
        )}
      </div>

      <ImportFormatDialog
        open={showFormat}
        onClose={() => setShowFormat(false)}
        onParsed={(questions) => {
          setExtractInfo(null);
          void applyExtraction(questions);
        }}
      />
    </div>
  );
}

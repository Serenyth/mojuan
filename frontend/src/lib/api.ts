import type {
  ExtractionScript,
  LoginResult,
  MeResult,
  Option,
  Question,
  QuestionType,
  SettingsResponse,
  User,
} from '@/lib/types';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = 'ApiError';
  }
}

function extractDetail(payload: unknown, status: number): string {
  const raw = (payload as { detail?: unknown } | null)?.detail;
  if (typeof raw === 'string') return raw;
  if (Array.isArray(raw)) {
    return raw
      .map((item) => (item as { msg?: string })?.msg)
      .filter(Boolean)
      .join('; ');
  }
  return `请求失败（${status}）`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: 'include',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, extractDetail(payload, response.status));
  }
  return payload as T;
}

export const api = {
  me: () => request<MeResult>('GET', '/api/auth/me'),
  login: (username: string, password: string) =>
    request<LoginResult>('POST', '/api/auth/login', { username, password }),
  register: (username: string, password: string, displayName: string) =>
    request<LoginResult>('POST', '/api/auth/register', { username, password, displayName }),
  logout: () => request<{ ok: boolean }>('POST', '/api/auth/logout'),

  getSettings: () => request<SettingsResponse>('GET', '/api/settings'),
  saveSettings: (patch: Record<string, string>) =>
    request<{ ok: boolean; settings: SettingsResponse['settings'] }>('PUT', '/api/settings', patch),
  testConnection: (payload: { baseUrl?: string; apiKey?: string; model?: string }) =>
    request<{ ok: boolean; message: string; models: string[] }>(
      'POST',
      '/api/settings/test-connection',
      payload,
    ),
  listModels: () => request<{ models: string[] }>('GET', '/api/settings/models'),
};

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export function adminOnly(user: User | null): boolean {
  return Boolean(user?.isAdmin);
}

// ============================================================
// 以下为 AI-A 追加：导入侧接口（材料 / 提取 / 批量入库）。
// 未改动上方任何已有代码。
// ============================================================

export type SourceKind = 'document' | 'image' | 'url' | 'text';

export interface ImportSource {
  id: string;
  type: SourceKind;
  name: string;
  status: string;
  error: string | null;
  charCount: number;
  createdAt: string;
  meta: Record<string, unknown>;
  preview?: string;
}

/** 提取出来的候选题。还没进题库，等人工审核勾选后才批量入库。 */
export interface CandidateQuestion {
  type: QuestionType;
  content: string;
  options: Option[] | null;
  answer: string[];
  acceptableAnswers?: string[][] | null;
  explanation: string | null;
  tags: string[];
  difficulty: number;
  confidence: number;
  fingerprint: string;
  suspect: boolean;
  duplicate?: boolean;
  issues: string[];
}

export interface ExtractionJob {
  id: string;
  sourceIds: string[];
  mode: string;
  status: string;
  scriptId: string | null;
  stats: Record<string, unknown>;
  createdAt: string;
}

export interface ExtractDirectResult {
  job: ExtractionJob;
  questions: CandidateQuestion[];
}

/** 阶段四：运行脚本的结果。失败时 ok=false、job=null，带 log 供调试脚本。 */
export interface ScriptRunResult {
  ok: boolean;
  job: ExtractionJob | null;
  questions: CandidateQuestion[];
  log: string;
  error: string | null;
}

export interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
}

/** extract_direct：前端自动触发提取；confirm：暂停等用户确认 */
export interface ExtractDirectAction {
  type: 'extract_direct';
  sourceIds: string[];
  urls?: string[];
  /** agent 已跑过 extract_questions：直接按 jobId 取候选，不必再打一次提取 */
  jobId?: string;
  instruction: string;
}

/** 暂停等用户确认：前端只展示说明，不自动执行，用户回复后继续对话 */
export interface ConfirmAction {
  type: 'confirm';
  /** 为什么卡住 / 打算做什么 */
  reason?: string;
  /** 下一步打算怎么做 */
  plan?: string;
}

export type ChatAction = ExtractDirectAction | ConfirmAction;

/** agent 的一步工具调用，渲染成对话流里的紧凑轨迹 */
export interface AgentStep {
  tool: string;
  ok: boolean;
  note: string;
  /** 这一步之前模型的思考（thought 字段 / 推理模型的 reasoning） */
  thought?: string;
  /** 这一步的总耗时（毫秒）：模型思考 + 工具执行 */
  ms?: number;
}

export interface ChatResult {
  reply: string;
  action: ChatAction | null;
  steps?: AgentStep[];
  /** 最终回复前的思考 */
  reasoning?: string;
  /** 整轮循环的总耗时（毫秒） */
  ms?: number;
}

/** 流式对话（POST /api/extract/chat/stream）推来的 SSE 事件 */
export type ChatEvent =
  | { type: 'conversation'; id: string }
  | { type: 'step'; tool: string; ok: boolean; note: string; thought?: string; ms?: number }
  | {
      type: 'reply';
      reply: string;
      thought?: string;
      action: ChatAction | null;
      ms_total?: number;
    }
  | { type: 'error'; message: string };

/** 会话记录列表里的一条 */
export interface Conversation {
  id: string;
  title: string;
  updatedAt: string;
  messageCount: number;
  lastMessage: string;
}

/** 会话里落库的一条消息：轨迹（step）与耗时都原样带回 */
export interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  kind: 'text' | 'step' | 'system';
  text: string;
  thought: string;
  tool: string;
  ok: boolean | null;
  ms: number | null;
  createdAt: string;
}

export const chatApi = {
  list: () => request<{ conversations: Conversation[] }>('GET', '/api/conversations'),

  create: (title: string) =>
    request<{ conversation: { id: string; title: string } }>('POST', '/api/conversations', { title }),

  get: (id: string) =>
    request<{ messages: ConversationMessage[] }>('GET', `/api/conversations/${id}`),

  remove: (id: string) => request<{ ok: boolean }>('DELETE', `/api/conversations/${id}`),

  /** 前端补写的系统气泡（提取结果摘要等）落库 */
  append: (id: string, payload: { role: 'assistant'; text: string }) =>
    request<{ ok: boolean }>('POST', `/api/conversations/${id}/messages`, {
      role: payload.role,
      kind: 'text',
      text: payload.text,
    }),

  /** 流式对话：返回原始 Response，由调用方读 body 解 SSE。
   *  scriptId 不为空时把该脚本代码注入对话，让 AI 改代码 / 跑沙盒调试。 */
  stream: (payload: { message: string; conversationId: string | null; sourceIds: string[]; scriptId?: string | null }) =>
    fetch('/api/extract/chat/stream', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
};

/** 与 request 的区别：发 multipart，不带 JSON 头 */
async function sendForm<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(path, { method: 'POST', credentials: 'include', body: form });
  return readResponse<T>(response);
}

async function readResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    throw new ApiError(response.status, extractDetail(payload, response.status));
  }
  return payload as T;
}

export const importApi = {
  listSources: () => request<{ sources: ImportSource[] }>('GET', '/api/sources'),

  uploadSource: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return sendForm<{ source: ImportSource }>('/api/sources', form);
  },

  addUrlSource: (url: string) => {
    const form = new FormData();
    form.append('url', url);
    return sendForm<{ source: ImportSource }>('/api/sources', form);
  },

  addTextSource: (text: string) => {
    const form = new FormData();
    form.append('text', text);
    return sendForm<{ source: ImportSource }>('/api/sources', form);
  },

  deleteSource: (id: string) => request<{ ok: boolean }>('DELETE', `/api/sources/${id}`),

  extractDirect: (payload: { sourceIds: string[]; instruction?: string }) =>
    request<ExtractDirectResult>('POST', '/api/extract/direct', payload),

  chat: (payload: { message: string; history: ChatTurn[]; sourceIds: string[] }) =>
    request<ChatResult>('POST', '/api/extract/chat', payload),

  getJob: (id: string) =>
    request<{ job: ExtractionJob; questions: CandidateQuestion[] }>('GET', `/api/extract/jobs/${id}`),

  confirmImport: (payload: { bankId: string; questions: CandidateQuestion[] }) =>
    request<{ created: number; questions: Question[] }>('POST', '/api/questions/batch', payload),

  /** 阶段四：用提取脚本跑一组材料（沙盒执行），返回候选题与日志 */
  runScript: (payload: { scriptId: string; sourceIds: string[] }) =>
    request<ScriptRunResult>('POST', '/api/extract/script', payload),

  /** 把外部 AI 整理好的题目文本（JSON 数组）解析成统一候选题：不调模型、不入库 */
  parse: (payload: { text: string }) =>
    request<{ questions: CandidateQuestion[] }>('POST', '/api/extract/parse', payload),
};

/** 阶段四：提取脚本的 CRUD 与 AI 生成脚手架 */
export const scriptApi = {
  list: () => request<{ scripts: ExtractionScript[] }>('GET', '/api/scripts'),

  get: (id: string) => request<{ script: ExtractionScript }>('GET', `/api/scripts/${id}`),

  create: (payload: { name: string; platform?: string; code: string; isShared?: boolean }) =>
    request<{ script: ExtractionScript }>('POST', '/api/scripts', payload),

  update: (
    id: string,
    patch: { name?: string; platform?: string; code?: string; isShared?: boolean },
  ) => request<{ script: ExtractionScript }>('PATCH', `/api/scripts/${id}`, patch),

  remove: (id: string) => request<{ ok: boolean }>('DELETE', `/api/scripts/${id}`),

  generate: (payload: { description: string; platform?: string }) =>
    request<{ code: string }>('POST', '/api/scripts/generate', payload),
};

// ============================================================
// 以下为 AI-B 追加：刷题侧接口。未改动上方任何已有代码。
// ============================================================

export interface Bank {
  id: string;
  name: string;
  platform: string | null;
  description: string | null;
  ownerId: string | null;
  isShared: boolean;
  createdAt: string;
  questionCount?: number;
  /** 'wrongbook' = 内置错题本题库：题目是错题的投影，不能改名/删除/加题 */
  kind?: string | null;
  /** 各题型的题量，组卷时按题型核对能不能抽够 */
  typeCounts?: Record<string, number>;
}

/** 刷题 / 考试场景的题目（响应中已剔除答案字段） */
export type PracticeQuestion = Omit<Question, 'answer'>;

/** 题库管理场景的题目（带答案解析，含 source 字段） */
export interface QuestionDetail extends Question {
  source?: string | null;
  /** 只有在内置错题本题库里列出来时才带：错题记录本身的信息 */
  wrongId?: string | null;
  wrongCount?: number | null;
  wrongStreak?: number | null;
  lastWrongAt?: string | null;
}

export interface QuestionsPage {
  items: QuestionDetail[];
  total: number;
  page: number;
  pageSize: number;
  tags: string[];
  typeCounts: Record<string, number>;
}

export interface QuestionInput {
  bankId: string;
  type: QuestionType;
  content: string;
  options?: Option[] | null;
  answer: string[] | string;
  acceptableAnswers?: string[][] | null;
  explanation?: string | null;
  tags?: string[];
  difficulty?: number;
  source?: string | null;
}

export type PracticeOrder = 'shuffle' | 'sequential';

export interface PracticeSessionInfo {
  id: string;
  mode: string;
  order: PracticeOrder;
  bankId: string | null;
  filters: Record<string, string>;
  total: number;
  answered: number;
  correct: number;
  pending: number;
  cursor: number;
  startedAt: string;
  finishedAt: string | null;
  finished: boolean;
}

export interface PracticeState {
  session: PracticeSessionInfo;
  current: PracticeQuestion | null;
  /** 会话全量题目（按出题顺序，无答案）——翻阅式作答一次拿整卷 */
  questions?: PracticeQuestion[];
  /** 已作答记录（按题目顺序）——刷新后据此恢复翻页状态 */
  records?: PracticeRecordView[];
}

export interface AnswerOutcome {
  correct: boolean | null;
  score: number | null;
  maxScore: number | null;
  detail: string;
  explanation: string | null;
  /** 本题正确答案：判分后随反馈返回，未作答前不泄漏 */
  answer: string[] | string | null;
}

export interface AnswerResult extends PracticeState {
  outcome: AnswerOutcome;
  recordId: string;
}

export interface FinishSummary {
  answered: number;
  correct: number;
  pending: number;
  accuracy: number | null;
}

/** 结算：会话结束后返回，questions 带答案，供逐题对照与阅卷 */
export interface PracticeFinishResult {
  session: PracticeSessionInfo;
  questions: Question[];
  records: PracticeRecordView[];
  summary: FinishSummary;
}

export interface WrongQuestionItem {
  id: string;
  wrongCount: number;
  correctStreak: number;
  mastered: boolean;
  lastWrongAt: string;
  question: PracticeQuestion;
}

export interface PracticeRecordView {
  id: string;
  sessionId: string | null;
  examId: string | null;
  userId: string;
  questionId: string;
  userAnswer: unknown;
  correct: boolean | null;
  score: number | null;
  maxScore: number | null;
  comment: string | null;
  judgedBy: string | null;
  judgedAt: string | null;
  timeSpent: number | null;
  createdAt: string;
  /** 已作答的题才带：刷新后判分反馈里的「正确答案」不丢 */
  answer?: string[] | string | null;
}

export interface ReviewItem {
  record: PracticeRecordView;
  question: Question;
}

export interface GradeResult {
  record: PracticeRecordView;
  passRatio: number;
  correct: boolean;
  intoWrongBook: boolean;
}

export interface ExamTemplate {
  id: string;
  name: string;
  ownerId: string | null;
  isShared: boolean;
  scopeBankId: string | null;
  scopeTags: string[];
  typeDistribution: Record<string, number>;
  totalCount: number;
  durationMinutes: number;
  shuffle: boolean;
  createdAt: string;
}

export interface TemplateInput {
  name: string;
  scopeBankId?: string | null;
  scopeTags?: string[];
  typeDistribution: Record<string, number>;
  totalCount: number;
  durationMinutes?: number;
  shuffle?: boolean;
  isShared?: boolean;
}

export type ExamStatus = 'ongoing' | 'submitted' | 'grading' | 'graded';

export interface ExamScores {
  objectiveScore: number;
  subjectiveScore: number;
  totalScore: number;
  objectiveMax: number;
  subjectiveMax: number;
  objectiveCount: number;
  subjectiveCount: number;
  gradedSubjective: number;
  pendingSubjective: number;
}

export interface ExamInfo {
  id: string;
  templateId: string | null;
  templateName: string | null;
  questionCount: number;
  durationMinutes: number;
  startedAt: string;
  deadline: string;
  submittedAt: string | null;
  status: ExamStatus;
  scores: ExamScores;
}

/** 概览「最近记录」：刷题会话与考试各取最近若干条 */
export interface PracticeHistoryItem {
  id: string;
  bankId: string | null;
  bankName: string | null;
  filters: Record<string, string>;
  order: string;
  total: number;
  answered: number;
  correct: number;
  startedAt: string;
  finishedAt: string | null;
}

export interface ExamHistoryItem {
  id: string;
  templateId: string | null;
  templateName: string | null;
  questionCount: number;
  durationMinutes: number | null;
  startedAt: string;
  submittedAt: string | null;
  status: ExamStatus;
  objectiveScore: number | null;
  subjectiveScore: number | null;
  totalScore: number | null;
  maxScore: number | null;
}

export interface HistoryResult {
  practice: PracticeHistoryItem[];
  exams: ExamHistoryItem[];
}

export interface ExamStartResult {
  exam: ExamInfo;
  questions: PracticeQuestion[];
}

export interface ExamSubmitResult {
  exam: ExamInfo;
  scores: ExamScores;
  unanswered: string[];
  overtime: boolean;
}

/** 考试快照：进行中恢复答题用，题目不带答案 */
export interface ExamSnapshot {
  exam: ExamInfo;
  questions: PracticeQuestion[];
  records: PracticeRecordView[];
  scores: ExamScores;
}

/** 考试结果：交卷后取，questions 带答案，供逐题对照与阅卷 */
export interface ExamResult extends ExamSnapshot {
  questions: Question[];
}

function toSearchParams(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '' && value !== false) search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

export const quizApi = {
  // —— 题库与题目 ——
  listBanks: () => request<{ banks: Bank[] }>('GET', '/api/banks'),
  createBank: (payload: { name: string; platform?: string; description?: string; isShared?: boolean }) =>
    request<{ bank: Bank }>('POST', '/api/banks', payload),
  updateBank: (id: string, patch: { name?: string; platform?: string; description?: string; isShared?: boolean }) =>
    request<{ bank: Bank }>('PATCH', `/api/banks/${id}`, patch),
  deleteBank: (id: string) => request<{ ok: boolean }>('DELETE', `/api/banks/${id}`),

  listQuestions: (
    bankId: string,
    params: { type?: string; tag?: string; keyword?: string; page?: number; pageSize?: number } = {},
  ) =>
    request<QuestionsPage>(
      'GET',
      `/api/banks/${bankId}/questions${toSearchParams({
        type: params.type,
        tag: params.tag,
        keyword: params.keyword,
        page: params.page && params.page > 1 ? params.page : undefined,
        pageSize: params.pageSize && params.pageSize !== 20 ? params.pageSize : undefined,
      })}`,
    ),
  createQuestion: (payload: QuestionInput) =>
    request<{ question: Question }>('POST', '/api/questions', payload),
  updateQuestion: (id: string, patch: Partial<QuestionInput>) =>
    request<{ question: Question }>('PATCH', `/api/questions/${id}`, patch),
  deleteQuestion: (id: string) => request<{ ok: boolean }>('DELETE', `/api/questions/${id}`),

  // —— 刷题 ——
  createSession: (payload: {
    scope?: string;
    order?: PracticeOrder;
    bankId?: string;
    filters?: Record<string, string>;
    limit?: number;
    /** 旧入口字段，留空走 scope × order */
    mode?: string;
  }) => request<PracticeState>('POST', '/api/practice/sessions', payload),
  getSession: (id: string) => request<PracticeState>('GET', `/api/practice/sessions/${id}`),
  answerQuestion: (id: string, payload: { questionId: string; answer: string | string[] | null; timeSpent?: number }) =>
    request<AnswerResult>('POST', `/api/practice/sessions/${id}/answer`, payload),
  finishSession: (id: string) =>
    request<PracticeFinishResult>('POST', `/api/practice/sessions/${id}/finish`),
  /** 回顾历史答卷：不改动会话状态 */
  practiceResult: (id: string) =>
    request<PracticeFinishResult>('GET', `/api/practice/sessions/${id}/result`),
  resumeSession: (id: string) => request<PracticeState>('GET', `/api/practice/sessions/${id}/resume`),
  listWrongQuestions: (params: { type?: string; tag?: string; bankId?: string; mastered?: boolean } = {}) =>
    request<{ items: WrongQuestionItem[] }>(
      'GET',
      `/api/wrong-questions${toSearchParams({
        type: params.type,
        tag: params.tag,
        bank_id: params.bankId,
        mastered: params.mastered ? true : undefined,
      })}`,
    ),
  deleteWrongQuestion: (id: string) => request<{ ok: boolean }>('DELETE', `/api/wrong-questions/${id}`),

  // —— 阅卷 ——
  listPendingReview: () => request<{ items: ReviewItem[] }>('GET', '/api/review/pending'),
  gradeReview: (recordId: string, payload: { score: number; comment?: string }) =>
    request<GradeResult>('POST', `/api/review/${recordId}/grade`, payload),

  // —— 考试 ——
  listTemplates: () => request<{ templates: ExamTemplate[] }>('GET', '/api/exam-templates'),
  createTemplate: (payload: TemplateInput) =>
    request<{ template: ExamTemplate }>('POST', '/api/exam-templates', payload),
  updateTemplate: (id: string, patch: Partial<TemplateInput>) =>
    request<{ template: ExamTemplate }>('PATCH', `/api/exam-templates/${id}`, patch),
  deleteTemplate: (id: string) => request<{ ok: boolean }>('DELETE', `/api/exam-templates/${id}`),
  startExam: (payload: { templateId: string }) =>
    request<ExamStartResult>('POST', '/api/exams/start', payload),
  submitExam: (id: string, payload: { answers: { questionId: string; answer: string | string[] | null; timeSpent?: number }[] }) =>
    request<ExamSubmitResult>('POST', `/api/exams/${id}/submit`, payload),
  examSnapshot: (id: string) => request<ExamSnapshot>('GET', `/api/exams/${id}/result`),
  examResult: (id: string) =>
    request<ExamResult>('GET', `/api/exams/${id}/result${toSearchParams({ include_answer: true })}`),

  // —— 记录 ——
  /** 不传 limit 返回全量记录 */
  history: (limit?: number) => request<HistoryResult>('GET', `/api/history${toSearchParams({ limit })}`),
  deleteHistory: (payload: { practice: string[]; exams: string[] }) =>
    request<{ deleted: { practice: number; exams: number } }>('POST', '/api/history/delete', payload),
};

/** 导出题目为文件下载（CSV / JSON） */
export async function exportQuestions(params: { bankId?: string; format?: 'csv' | 'json' } = {}): Promise<void> {
  const response = await fetch(
    `/api/questions/export${toSearchParams({ bank_id: params.bankId, format: params.format ?? 'csv' })}`,
    { credentials: 'include' },
  );
  if (!response.ok) {
    let detail = `导出失败（${response.status}）`;
    try {
      const payload = await response.json();
      if (typeof payload?.detail === 'string') detail = payload.detail;
    } catch {
      /* 忽略非 JSON 响应体 */
    }
    throw new ApiError(response.status, detail);
  }
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const match = disposition.match(/filename="?([^"]+)"?/);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = match?.[1] ?? 'questions.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

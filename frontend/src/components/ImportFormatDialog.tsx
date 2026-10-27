import { useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Textarea } from '@/components/ui/Form';
import { Portal } from '@/components/ui/Portal';
import { importApi, isApiError, type CandidateQuestion } from '@/lib/api';
import { cn } from '@/lib/cn';

/** 后端 parse 的文本上限（字符），本地先挡一下给友好提示 */
const MAX_CHARS = 200_000;

/** 交给外部 AI 的提示词：让它把任意内容整理成墨卷能直接吃的 JSON 数组 */
const EXTRACT_PROMPT = `你是题库整理助手。请把我给你的内容整理成结构化题目，严格按下面的格式输出。

只输出一个 JSON 数组（不要解释、不要 Markdown 代码围栏）；没有题目时输出 []。

每个元素字段：
- type: "single_choice" | "multiple_choice" | "true_false" | "fill_blank" | "subjective"
- content: 题干原文，保留专业术语，去掉题号（如 "1." "（3）"）
- options: 选项数组 [{"key":"A","text":"..."}, ...]；判断题、填空题、主观题传 null
- answer: 单选 ["A"]、多选 ["A","C"]、判断 ["T"] 或 ["F"]、填空与主观题填字符串数组
- acceptableAnswers: 填空题的等价答案，形如 [["勾股定理","毕达哥拉斯定理"]]；没有就 null
- explanation: 答案解析，没有就 null
- tags: 主题标签数组，如 ["代数","初二"]；没有就 []
- difficulty: 1 到 5 的整数，5 最难
- confidence: 0 到 1 的小数，抽取准确性的自评；看不全就往低给

示例：
[
  {
    "type": "single_choice",
    "content": "中国的首都是？",
    "options": [{"key":"A","text":"上海"},{"key":"B","text":"北京"}],
    "answer": ["B"],
    "explanation": "北京是中华人民共和国的首都。",
    "tags": ["地理"],
    "difficulty": 1,
    "confidence": 0.95
  }
]

注意：
- 题干与选项必须原样保留，不要改写、不要补充材料里没有的信息
- 答案须是材料里明确给出或可直接推出的，推不出来就给 confidence 低一点
- 一个材料里出现多个小问，拆成多道题`;

function IconCopy(p: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={p.className} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </svg>
  );
}

interface Props {
  open: boolean;
  onClose: () => void;
  onParsed: (questions: CandidateQuestion[]) => void;
}

export function ImportFormatDialog({ open, onClose, onParsed }: Props) {
  const [copied, setCopied] = useState(false);
  const [text, setText] = useState('');
  const [parsing, setParsing] = useState(false);
  const [result, setResult] = useState<{ count: number; suspect: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState('');
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  if (!open) return null;

  async function copyPrompt() {
    try {
      await navigator.clipboard.writeText(EXTRACT_PROMPT);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError('复制失败，请手动选择上方文本复制');
    }
  }

  async function parseNow(raw?: string) {
    const source = raw ?? text;
    if (!source.trim()) {
      setError('先粘贴内容，或选择一个 .md / .json 文件');
      return;
    }
    setParsing(true);
    setError(null);
    setResult(null);
    try {
      const res = await importApi.parse({ text: source });
      const suspect = res.questions.filter((item) => item.suspect || item.issues.length).length;
      setResult({ count: res.questions.length, suspect });
      onParsed(res.questions);
    } catch (e) {
      setError(isApiError(e) ? e.detail : e instanceof Error ? e.message : '解析失败');
    } finally {
      setParsing(false);
    }
  }

  /** 读入 .md / .json 文件：文本进输入框，并直接走一遍解析 */
  function readFile(file: File) {
    const name = file.name.toLowerCase();
    const byExt =
      name.endsWith('.json') || name.endsWith('.md') || name.endsWith('.markdown');
    if (!byExt) {
      setError('只支持导入 .json / .md 文件');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const content = String(reader.result ?? '');
      if (content.length > MAX_CHARS) {
        setError(`文件过大（${content.length} 字），请拆分后再导入（上限 ${MAX_CHARS} 字）`);
        return;
      }
      setText(content);
      setFileName(file.name);
      setResult(null);
      setError(null);
      void parseNow(content);
    };
    reader.onerror = () => setError('读取文件失败');
    reader.readAsText(file, 'utf-8');
  }

  return (
    <Portal>
      <div
        className="fixed inset-0 z-50 grid place-items-center bg-canvas/80 p-4"
        role="dialog"
        aria-modal="true"
        onClick={onClose}
      >
      <div
        className="max-h-[88vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-line bg-surface p-5 shadow-overlay"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-[16px] font-semibold text-ink">数据格式 · 导入提示词</h2>
            <p className="mt-0.5 text-[12px] text-ink-faint">
              把提示词交给外部 AI，再把结果粘贴或选文件导入（.md / .json）
            </p>
          </div>
          <button
            type="button"
            aria-label="关闭"
            onClick={onClose}
            className="focus-ring rounded px-2 text-xl leading-none text-ink-faint transition-colors hover:text-ink"
          >
            ×
          </button>
        </div>

        <section className="mt-4">
          <div className="mb-2 flex items-center justify-between gap-3">
            <h3 className="text-[13px] font-medium text-ink-muted">可复制的提示词</h3>
            <Button size="sm" variant="secondary" onClick={() => void copyPrompt()}>
              <IconCopy className="h-4 w-4" />
              {copied ? '已复制' : '复制提示词'}
            </Button>
          </div>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-anywhere rounded-md border border-line-soft bg-sunken p-3 font-mono text-[12px] leading-relaxed text-ink-muted">
            {EXTRACT_PROMPT}
          </pre>
        </section>

        <section className="mt-5 border-t border-line-soft pt-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-[13px] font-medium text-ink-muted">粘贴或导入文件</h3>
            <div className="flex items-center gap-2">
              <input
                ref={fileRef}
                type="file"
                accept=".json,.md,.markdown,application/json,text/markdown"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) readFile(file);
                  event.target.value = '';
                }}
              />
              <Button
                size="sm"
                variant="secondary"
                onClick={() => fileRef.current?.click()}
                disabled={parsing}
              >
                选择文件（.md / .json）
              </Button>
            </div>
          </div>
          {fileName ? (
            <p className="mb-1.5 truncate text-[12px] text-ink-faint">已读取：{fileName}</p>
          ) : null}
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              const file = event.dataTransfer.files?.[0];
              if (file) readFile(file);
            }}
            className={cn('rounded-md transition-shadow', dragging && 'ring-2 ring-primary/40')}
          >
            <Textarea
              value={text}
              spellCheck={false}
              onChange={(event) => {
                setText(event.target.value);
                setFileName('');
                setResult(null);
                setError(null);
              }}
              placeholder="把外部 AI 的 JSON（可带 ```json 围栏）粘到这里，或把 .md / .json 文件拖进来"
              className="min-h-[9rem] font-mono text-[12px] leading-relaxed"
            />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button variant="primary" onClick={() => void parseNow()} disabled={parsing}>
              {parsing ? '解析中' : '解析并载入'}
            </Button>
            {result ? (
              <span className="text-[12.5px] text-success-deep">
                已载入 {result.count} 题（存疑 {result.suspect}）
              </span>
            ) : null}
          </div>
          {error ? (
            <div className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-anywhere rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-[12.5px] leading-relaxed text-danger-deep">
              {error}
            </div>
          ) : null}
        </section>
      </div>
      </div>
    </Portal>
  );
}

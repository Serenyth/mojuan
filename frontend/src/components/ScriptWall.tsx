import { useEffect, useRef, useState } from 'react';
import { Badge, Card, Panel } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Field, Input, Select, Textarea } from '@/components/ui/Form';
import { Switch } from '@/components/ui/Switch';
import { Portal } from '@/components/ui/Portal';
import { IconPlay, IconPlus, IconTrash } from '@/components/ui/icons';
import { CandidateCard, Checkbox, type Candidate } from '@/components/CandidateCard';
import {
  importApi,
  isApiError,
  quizApi,
  scriptApi,
  type Bank,
  type ImportSource,
  type ScriptRunResult,
} from '@/lib/api';
import type { ExtractionScript } from '@/lib/types';

const NEW_TEMPLATE = `import mojuan

questions = []
for src in mojuan.sources:
    text = src["text"]
    # 解析 text，构造题目 dict 后 append：
    # {"type": "single_choice", "content": "...", "options": [...], "answer": ["A"], ...}
    # questions.append({...})

mojuan.emit(questions)
`;

interface FormState {
  name: string;
  platform: string;
  code: string;
  isShared: boolean;
}

const EMPTY_FORM: FormState = { name: '', platform: '', code: NEW_TEMPLATE, isShared: true };

function errorText(error: unknown): string {
  if (isApiError(error)) return error.detail;
  return error instanceof Error ? error.message : '操作失败';
}

/** 把脚本「加入对话」的图标：对话气泡，直观表达交给 AI 调试 */
function IconChat(p: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={p.className} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 9 9 0 0 1-3.9-.9L3 21l1.9-5.6A8.38 8.38 0 0 1 4 11.5 8.5 8.5 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5z" />
    </svg>
  );
}

export function ScriptWall({ onAttach }: { onAttach: (script: ExtractionScript) => void }) {
  const [scripts, setScripts] = useState<ExtractionScript[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [sources, setSources] = useState<ImportSource[]>([]);
  const [banks, setBanks] = useState<Bank[]>([]);

  const [editing, setEditing] = useState<ExtractionScript | 'new' | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [editorError, setEditorError] = useState<string | null>(null);
  const [genDesc, setGenDesc] = useState('');
  const [generating, setGenerating] = useState(false);

  const [running, setRunning] = useState<ExtractionScript | null>(null);
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set());
  const [bankId, setBankId] = useState('');
  const [newBankName, setNewBankName] = useState('');
  const [creatingBank, setCreatingBank] = useState(false);
  const [runBusy, setRunBusy] = useState(false);
  const [runResult, setRunResult] = useState<ScriptRunResult | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [importing, setImporting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const keySeq = useRef(0);

  useEffect(() => {
    void loadAll();
  }, []);

  async function loadAll() {
    setLoading(true);
    setLoadError(null);
    try {
      const [scriptRes, sourceRes, bankRes] = await Promise.all([
        scriptApi.list(),
        importApi.listSources(),
        quizApi.listBanks(),
      ]);
      setScripts(scriptRes.scripts);
      setSources(sourceRes.sources);
      setBanks(bankRes.banks);
      setBankId((prev) => prev || bankRes.banks[0]?.id || '');
    } catch (error) {
      setLoadError(errorText(error));
    } finally {
      setLoading(false);
    }
  }

  function startNew() {
    setEditing('new');
    setForm(EMPTY_FORM);
    setEditorError(null);
    setGenDesc('');
  }

  function startEdit(script: ExtractionScript) {
    setEditing(script);
    setForm({
      name: script.name,
      platform: script.platform,
      code: script.code,
      isShared: script.isShared,
    });
    setEditorError(null);
    setGenDesc('');
  }

  async function saveScript() {
    if (!form.name.trim()) {
      setEditorError('请填写脚本名称');
      return;
    }
    if (!form.code.trim()) {
      setEditorError('脚本内容不能为空');
      return;
    }
    setSaving(true);
    setEditorError(null);
    try {
      if (editing === 'new') {
        const res = await scriptApi.create({
          name: form.name.trim(),
          platform: form.platform.trim(),
          code: form.code,
          isShared: form.isShared,
        });
        setScripts((prev) => [res.script, ...prev]);
      } else if (editing) {
        const res = await scriptApi.update(editing.id, {
          name: form.name.trim(),
          platform: form.platform.trim(),
          code: form.code,
          isShared: form.isShared,
        });
        setScripts((prev) => prev.map((item) => (item.id === res.script.id ? res.script : item)));
      }
      setEditing(null);
    } catch (error) {
      setEditorError(errorText(error));
    } finally {
      setSaving(false);
    }
  }

  async function generateCode() {
    if (!genDesc.trim()) {
      setEditorError('先写一句需求描述');
      return;
    }
    setGenerating(true);
    setEditorError(null);
    try {
      const res = await scriptApi.generate({
        description: genDesc.trim(),
        platform: form.platform.trim(),
      });
      setForm((prev) => ({ ...prev, code: res.code }));
    } catch (error) {
      setEditorError(errorText(error));
    } finally {
      setGenerating(false);
    }
  }

  async function removeScript(script: ExtractionScript) {
    if (!window.confirm(`删除脚本「${script.name}」？`)) return;
    try {
      await scriptApi.remove(script.id);
      setScripts((prev) => prev.filter((item) => item.id !== script.id));
    } catch (error) {
      setLoadError(errorText(error));
    }
  }

  function openRun(script: ExtractionScript) {
    setRunning(script);
    setSelectedSources(new Set());
    setRunResult(null);
    setCandidates([]);
    setChecked(new Set());
    setNotice(null);
  }

  function toggleSource(id: string) {
    setSelectedSources((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function runNow() {
    if (!running) return;
    if (selectedSources.size === 0) {
      setNotice('先勾选至少一份材料');
      return;
    }
    setRunBusy(true);
    setNotice(null);
    try {
      const res = await importApi.runScript({
        scriptId: running.id,
        sourceIds: [...selectedSources],
      });
      setRunResult(res);
      if (res.ok) {
        const mapped: Candidate[] = res.questions.map((question) => ({
          ...question,
          key: `c${keySeq.current++}-${question.fingerprint}-${Math.random().toString(36).slice(2, 6)}`,
        }));
        setCandidates(mapped);
        setChecked(new Set(mapped.filter((item) => !item.duplicate).map((item) => item.key)));
        setNotice(`脚本跑完：${res.questions.length} 题`);
      } else {
        setCandidates([]);
        setChecked(new Set());
        setNotice(null);
      }
    } catch (error) {
      setRunResult({ ok: false, job: null, questions: [], log: '', error: errorText(error) });
      setCandidates([]);
      setChecked(new Set());
    } finally {
      setRunBusy(false);
    }
  }

  async function createBank() {
    if (!newBankName.trim()) return;
    setCreatingBank(true);
    try {
      const res = await quizApi.createBank({ name: newBankName.trim() });
      setBanks((prev) => [...prev, res.bank]);
      setBankId(res.bank.id);
      setNewBankName('');
    } catch (error) {
      setNotice(errorText(error));
    } finally {
      setCreatingBank(false);
    }
  }

  function toggleCandidate(key: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function removeCandidate(key: string) {
    setCandidates((prev) => prev.filter((item) => item.key !== key));
    setChecked((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  }

  async function importChosen() {
    const chosen = candidates.filter((item) => checked.has(item.key));
    if (!chosen.length || !bankId) return;
    setImporting(true);
    try {
      const payload = chosen.map((item) => {
        const { key: _drop, ...question } = item;
        return question;
      });
      const res = await importApi.confirmImport({ bankId, questions: payload });
      setCandidates([]);
      setChecked(new Set());
      setNotice(`已导入 ${res.created} 题`);
      const bankRes = await quizApi.listBanks();
      setBanks(bankRes.banks);
    } catch (error) {
      setNotice(`入库失败：${errorText(error)}`);
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="min-h-0 overflow-y-auto">
      <div className="flex items-center justify-between gap-3 px-1 pb-3">
        <p className="text-[12.5px] leading-relaxed text-ink-faint">
          同源页面反复用的提取脚本，在无网络沙盒里运行。需要让 AI 改代码或调试，点「加入对话」。
        </p>
        <Button variant="primary" onClick={startNew}>
          <IconPlus className="h-4 w-4" />
          新建脚本
        </Button>
      </div>

      {editing ? (
        <div className="mb-5">
          <Panel
            title={editing === 'new' ? '新建脚本' : `编辑脚本 · v${editing.version}`}
            action={
              <Button variant="ghost" size="sm" onClick={() => setEditing(null)}>
                取消
              </Button>
            }
          >
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_200px]">
                <Field label="名称">
                  <Input
                    value={form.name}
                    placeholder="例如：某题库网站 · 单选提取"
                    onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
                  />
                </Field>
                <Field label="平台（可选）">
                  <Input
                    value={form.platform}
                    placeholder="例如：某某题库"
                    onChange={(event) => setForm((prev) => ({ ...prev, platform: event.target.value }))}
                  />
                </Field>
              </div>

              <div className="flex items-center justify-between gap-4">
                <span className="text-[13px] text-ink">共享给其他用户</span>
                <Switch
                  label="共享给其他用户"
                  checked={form.isShared}
                  onChange={(next) => setForm((prev) => ({ ...prev, isShared: next }))}
                />
              </div>

              <Field label="脚本代码">
                <Textarea
                  value={form.code}
                  spellCheck={false}
                  style={{ minHeight: '20rem' }}
                  className="font-mono text-[12.5px] leading-relaxed"
                  onChange={(event) => setForm((prev) => ({ ...prev, code: event.target.value }))}
                />
              </Field>

              <div className="flex flex-wrap items-center gap-2">
                <Input
                  value={genDesc}
                  className="min-w-[240px] flex-1"
                  placeholder="用一句话说明要抓的页面 / 格式，让 AI 生成脚本骨架"
                  onChange={(event) => setGenDesc(event.target.value)}
                />
                <Button variant="secondary" size="sm" onClick={() => void generateCode()} disabled={generating}>
                  {generating ? '生成中' : 'AI 生成'}
                </Button>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <Button variant="primary" onClick={() => void saveScript()} disabled={saving}>
                  {saving ? '保存中' : '保存'}
                </Button>
                <Button variant="ghost" onClick={() => setEditing(null)}>
                  取消
                </Button>
                {editorError ? (
                  <span className="text-[12.5px] text-danger-deep">{editorError}</span>
                ) : null}
              </div>
            </div>
          </Panel>
        </div>
      ) : null}

      {loadError ? (
        <p className="mb-4 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-[13px] text-danger-deep">
          {loadError}
        </p>
      ) : null}

      {loading ? (
        <p className="text-[13px] text-ink-faint">载入中</p>
      ) : scripts.length === 0 ? (
        <Card className="grid place-items-center gap-3 py-16 text-center">
          <p className="text-[14px] text-ink-muted">还没有脚本</p>
          <p className="max-w-md text-[12.5px] leading-relaxed text-ink-faint">
            写一段 Python 把材料文本转成题目，或让 AI 先生成骨架，再在「运行」里挑材料执行。
          </p>
          <Button variant="primary" onClick={startNew}>
            <IconPlus className="h-4 w-4" />
            新建脚本
          </Button>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {scripts.map((script) => (
            <Card key={script.id} className="flex flex-col gap-3 p-4">
              <div className="min-w-0">
                <h3 className="truncate text-[15px] font-semibold text-ink">{script.name}</h3>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  {script.platform ? <Badge tone="neutral">{script.platform}</Badge> : null}
                  <Badge tone="info">v{script.version}</Badge>
                  <Badge tone={script.isShared ? 'success' : 'neutral'}>
                    {script.isShared ? '共享' : '私有'}
                  </Badge>
                </div>
              </div>

              <pre className="max-h-24 overflow-hidden whitespace-pre-wrap break-anywhere rounded-md bg-sunken px-2.5 py-2 font-mono text-[11.5px] leading-relaxed text-ink-muted">
                {script.code.slice(0, 220)}
              </pre>

              <div className="mt-auto flex flex-wrap items-center gap-2 pt-1">
                <Button size="sm" variant="primary" onClick={() => openRun(script)}>
                  <IconPlay className="h-4 w-4" />
                  运行
                </Button>
                {script.canEdit ? (
                  <Button size="sm" variant="secondary" onClick={() => startEdit(script)}>
                    编辑
                  </Button>
                ) : null}
                <Button size="sm" variant="secondary" onClick={() => onAttach(script)} title="交给 AI 改代码或调试">
                  <IconChat className="h-4 w-4" />
                  加入对话
                </Button>
                {script.canEdit ? (
                  <button
                    type="button"
                    aria-label="删除脚本"
                    onClick={() => void removeScript(script)}
                    className="focus-ring ml-auto rounded p-1.5 text-ink-faint transition-colors hover:text-danger"
                  >
                    <IconTrash className="h-4 w-4" />
                  </button>
                ) : null}
              </div>
            </Card>
          ))}
        </div>
      )}

      {running ? (
        <Portal>
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-canvas/80 p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="max-h-[88vh] w-full max-w-3xl overflow-y-auto rounded-lg border border-line bg-surface p-5 shadow-overlay">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 className="truncate text-[16px] font-semibold text-ink">
                  运行「{running.name}」
                </h2>
                <p className="mt-0.5 text-[12px] text-ink-faint">无网络沙盒 · 最长 60 秒</p>
              </div>
              <button
                type="button"
                aria-label="关闭"
                onClick={() => setRunning(null)}
                className="focus-ring rounded px-2 text-xl leading-none text-ink-faint transition-colors hover:text-ink"
              >
                ×
              </button>
            </div>

            <div className="mt-4">
              <p className="mb-2 text-[12px] font-medium text-ink-muted">
                选择材料（{selectedSources.size}/{sources.length}）
              </p>
              <div className="max-h-44 space-y-0.5 overflow-y-auto rounded-md border border-line p-2">
                {sources.length ? (
                  sources.map((source) => (
                    <label
                      key={source.id}
                      className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 transition-colors hover:bg-sunken/60"
                    >
                      <Checkbox
                        checked={selectedSources.has(source.id)}
                        onToggle={() => toggleSource(source.id)}
                        label={`选择材料 ${source.name}`}
                      />
                      <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink">{source.name}</span>
                      <span className="shrink-0 font-mono text-[11px] text-ink-faint">
                        {source.charCount} 字
                      </span>
                    </label>
                  ))
                ) : (
                  <p className="px-1 py-2 text-[12.5px] text-ink-faint">
                    还没有材料，先到「导入」页添加。
                  </p>
                )}
              </div>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Field label="导入到题库">
                <Select value={bankId} onChange={(event) => setBankId(event.target.value)}>
                  {banks.length ? (
                    banks.map((bank) => (
                      <option key={bank.id} value={bank.id}>
                        {bank.name}
                      </option>
                    ))
                  ) : (
                    <option value="">（暂无题库）</option>
                  )}
                </Select>
              </Field>
              {banks.length ? null : (
                <Field label="新建题库">
                  <div className="flex gap-2">
                    <Input
                      value={newBankName}
                      placeholder="题库名称"
                      onChange={(event) => setNewBankName(event.target.value)}
                    />
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => void createBank()}
                      disabled={creatingBank}
                    >
                      创建
                    </Button>
                  </div>
                </Field>
              )}
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button
                variant="primary"
                onClick={() => void runNow()}
                disabled={runBusy || selectedSources.size === 0}
              >
                {runBusy ? '运行中' : '运行脚本'}
              </Button>
              {notice ? <span className="text-[12.5px] text-ink-muted">{notice}</span> : null}
            </div>

            {runResult && !runResult.ok ? (
              <div className="mt-4 rounded-md border border-danger/30 bg-danger/10 p-3">
                <p className="text-[13px] font-medium text-danger-deep">
                  {runResult.error || '脚本执行失败'}
                </p>
                {runResult.log ? (
                  <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-anywhere rounded bg-sunken p-2 font-mono text-[11.5px] leading-relaxed text-ink-muted">
                    {runResult.log}
                  </pre>
                ) : null}
              </div>
            ) : null}

            {runResult && runResult.ok ? (
              <div className="mt-4">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <p className="text-[12px] font-medium text-ink-muted">
                    候选题（{candidates.length}）
                  </p>
                  {runResult.log ? (
                    <details className="text-[11.5px] text-ink-faint">
                      <summary className="cursor-pointer select-none">运行日志</summary>
                      <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-anywhere rounded bg-sunken p-2 font-mono text-[11px] leading-relaxed">
                        {runResult.log}
                      </pre>
                    </details>
                  ) : null}
                </div>

                {candidates.length ? (
                  <>
                    <ul className="space-y-1.5">
                      {candidates.map((candidate) => (
                        <CandidateCard
                          key={candidate.key}
                          candidate={candidate}
                          checked={checked.has(candidate.key)}
                          onToggle={() => toggleCandidate(candidate.key)}
                          onRemove={() => removeCandidate(candidate.key)}
                        />
                      ))}
                    </ul>
                    <div className="mt-3">
                      <Button
                        variant="primary"
                        onClick={() => void importChosen()}
                        disabled={importing || checked.size === 0 || !bankId}
                      >
                        {importing ? '入库中' : `导入选中 ${checked.size} 题`}
                      </Button>
                    </div>
                  </>
                ) : (
                  <p className="text-[12.5px] text-ink-faint">
                    脚本没有产出题目，检查脚本逻辑或换材料再试。
                  </p>
                )}
              </div>
            ) : null}
          </div>
        </div>
        </Portal>
      ) : null}
    </div>
  );
}

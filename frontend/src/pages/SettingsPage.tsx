import { useEffect, useState } from 'react';
import { useAuth } from '@/auth';
import { api, isApiError } from '@/lib/api';
import { PageTitle } from '@/components/AppShell';
import { Badge, Panel } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Field, Input, Textarea } from '@/components/ui/Form';
import { Switch } from '@/components/ui/Switch';
import { cn } from '@/lib/cn';
import type { Settings } from '@/lib/types';

const MASK = '********';

const EDITABLE_KEYS: Array<keyof Settings> = [
  'ai_base_url',
  'ai_api_key',
  'ai_model',
  'ai_vision_model',
  'multiple_partial_credit',
  'multiple_partial_ratio',
  'fill_ignore_case',
  'subjective_max_score',
  'subjective_pass_ratio',
  'master_streak',
  'agent_system_prompt',
];

interface TestResult {
  ok: boolean;
  text: string;
  models: string[];
}

export function SettingsPage() {
  const { user } = useAuth();
  const canEdit = Boolean(user?.isAdmin);

  const [saved, setSaved] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);

  useEffect(() => {
    api
      .getSettings()
      .then((result) => {
        setSaved(result.settings);
        setDraft(result.settings);
      })
      .catch((caught: unknown) => {
        setLoadError(isApiError(caught) ? caught.detail : '设置载入失败');
      });
  }, []);

  function update(key: keyof Settings, value: string) {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
    setSavedFlash(false);
  }

  async function handleSave() {
    if (!saved || !draft) return;
    setSaveError(null);
    setSaving(true);

    const patch: Record<string, string> = {};
    for (const key of EDITABLE_KEYS) {
      if (draft[key] !== saved[key] && draft[key] !== MASK) {
        patch[key] = draft[key];
      }
    }

    if (Object.keys(patch).length === 0) {
      setSaveError('没有改动');
      setSaving(false);
      return;
    }

    try {
      const result = await api.saveSettings(patch);
      setSaved(result.settings);
      setDraft(result.settings);
      setSavedFlash(true);
      setTest(null);
    } catch (caught) {
      setSaveError(isApiError(caught) ? caught.detail : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    if (!draft) return;
    setTesting(true);
    setTest(null);
    try {
      const result = await api.testConnection({
        baseUrl: draft.ai_base_url || undefined,
        apiKey: draft.ai_api_key === MASK ? undefined : draft.ai_api_key || undefined,
        model: draft.ai_model || undefined,
      });
      setTest({ ok: true, text: result.message, models: result.models });
    } catch (caught) {
      setTest({ ok: false, text: isApiError(caught) ? caught.detail : '连接失败', models: [] });
    } finally {
      setTesting(false);
    }
  }

  if (loadError) {
    return (
      <div>
        <PageTitle title="设置" />
        <p className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-[13px] text-danger-deep">
          {loadError}
        </p>
      </div>
    );
  }

  if (!saved || !draft) {
    return (
      <div>
        <PageTitle title="设置" />
        <p className="text-[13px] text-ink-faint">载入中</p>
      </div>
    );
  }

  const partialCredit = draft.multiple_partial_credit === 'true';
  const keyConfigured = draft.ai_api_key_configured === 'true';
  const dirty = EDITABLE_KEYS.some(
    (key) => draft[key] !== saved[key] && draft[key] !== MASK,
  );

  return (
    <div>
      <PageTitle title="设置" subtitle="模型接口与判分规则为全局设置" />

      <div className="space-y-5">
        <Panel
          title="模型接口"
          action={
            !canEdit ? (
              <Badge tone="neutral">仅管理员可修改</Badge>
            ) : keyConfigured ? (
              <Badge tone="success">密钥已保存</Badge>
            ) : (
              <Badge tone="warning">未配置密钥</Badge>
            )
          }
        >
          <div className="space-y-4">
            <Field label="Base URL">
              <Input
                value={draft.ai_base_url}
                disabled={!canEdit}
                placeholder="https://api.openai.com/v1"
                onChange={(event) => update('ai_base_url', event.target.value)}
              />
            </Field>

            <Field label="API Key">
              <Input
                type="password"
                value={draft.ai_api_key}
                disabled={!canEdit}
                placeholder="sk-..."
                onChange={(event) => update('ai_api_key', event.target.value)}
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="文本模型">
                <Input
                  value={draft.ai_model}
                  disabled={!canEdit}
                  placeholder="gpt-4o-mini"
                  onChange={(event) => update('ai_model', event.target.value)}
                />
              </Field>
              <Field label="视觉模型">
                <Input
                  value={draft.ai_vision_model}
                  disabled={!canEdit}
                  placeholder="gpt-4o"
                  onChange={(event) => update('ai_vision_model', event.target.value)}
                />
              </Field>
            </div>

            {canEdit ? (
              <div className="flex items-center gap-3 pt-1">
                <Button variant="secondary" size="sm" onClick={handleTest} disabled={testing}>
                  {testing ? '测试中' : '测试连接'}
                </Button>
                {test ? (
                  <span className={cn('text-[13px] font-medium', test.ok ? 'text-success-deep' : 'text-danger-deep')}>
                    {test.text}
                    {test.models.length ? ` · 可用模型 ${test.models.length} 个` : ''}
                  </span>
                ) : null}
              </div>
            ) : null}

            {test?.models.length ? (
              <div className="border-t border-line pt-4">
                <p className="mb-2.5 text-[12px] text-ink-faint">点击选用</p>
                <div className="flex flex-wrap gap-1.5">
                  {test.models.slice(0, 24).map((model) => (
                    <button
                      key={model}
                      type="button"
                      disabled={!canEdit}
                      onClick={() => update('ai_model', model)}
                      className="focus-ring rounded-full border border-line bg-surface px-2.5 py-1 font-mono text-[11px] text-ink-muted transition-colors duration-150 hover:border-primary/50 hover:text-primary disabled:pointer-events-none"
                    >
                      {model}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </Panel>

        <Panel
          title="导入助手提示词"
          action={
            !canEdit ? (
              <Badge tone="neutral">仅管理员可修改</Badge>
            ) : draft.agent_system_prompt === draft.agent_system_prompt_default ? (
              <Badge tone="neutral">内置默认</Badge>
            ) : (
              <Badge tone="violet">已自定义</Badge>
            )
          }
        >
          <div className="space-y-3">
            <Field label="系统提示词">
              <Textarea
                value={draft.agent_system_prompt}
                disabled={!canEdit}
                style={{ minHeight: '18rem' }}
                className="font-mono text-[12.5px] leading-relaxed"
                onChange={(event) => update('agent_system_prompt', event.target.value)}
              />
            </Field>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="secondary"
                size="sm"
                disabled={
                  !canEdit || draft.agent_system_prompt === draft.agent_system_prompt_default
                }
                onClick={() => update('agent_system_prompt', draft.agent_system_prompt_default)}
              >
                恢复默认
              </Button>
              <span className="text-[12px] text-ink-faint">保存后对导入对话生效</span>
            </div>
          </div>
        </Panel>

        <Panel title="判分规则">
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-4">
              <span className="text-[13px] text-ink">多选题漏选给部分分</span>
              <Switch
                label="多选题漏选给部分分"
                checked={partialCredit}
                disabled={!canEdit}
                onChange={(next) => update('multiple_partial_credit', next ? 'true' : 'false')}
              />
            </div>

            {partialCredit ? (
              <Field label="漏选得分比例" hint="0–1 之间">
                <Input
                  value={draft.multiple_partial_ratio}
                  disabled={!canEdit}
                  inputMode="decimal"
                  onChange={(event) => update('multiple_partial_ratio', event.target.value)}
                />
              </Field>
            ) : null}

            <div className="flex items-center justify-between gap-4">
              <span className="text-[13px] text-ink">填空题忽略大小写</span>
              <Switch
                label="填空题忽略大小写"
                checked={draft.fill_ignore_case === 'true'}
                disabled={!canEdit}
                onChange={(next) => update('fill_ignore_case', next ? 'true' : 'false')}
              />
            </div>

            <div className="grid gap-4 border-t border-line pt-4 sm:grid-cols-3">
              <Field label="主观题满分">
                <Input
                  value={draft.subjective_max_score}
                  disabled={!canEdit}
                  inputMode="numeric"
                  onChange={(event) => update('subjective_max_score', event.target.value)}
                />
              </Field>
              <Field label="及格比例" hint="低于此值进错题本">
                <Input
                  value={draft.subjective_pass_ratio}
                  disabled={!canEdit}
                  inputMode="decimal"
                  onChange={(event) => update('subjective_pass_ratio', event.target.value)}
                />
              </Field>
              <Field label="掌握所需连对数">
                <Input
                  value={draft.master_streak}
                  disabled={!canEdit}
                  inputMode="numeric"
                  onChange={(event) => update('master_streak', event.target.value)}
                />
              </Field>
            </div>
          </div>
        </Panel>

        {canEdit ? (
          <div className="flex items-center gap-3">
            <Button variant="primary" onClick={handleSave} disabled={saving || !dirty}>
              {saving ? '保存中' : '保存'}
            </Button>
            {savedFlash ? <span className="text-[13px] font-medium text-success-deep">已保存</span> : null}
            {saveError ? (
              <span className="text-[13px] font-medium text-danger-deep">{saveError}</span>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

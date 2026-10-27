import { useState, type FormEvent } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '@/auth';
import { api, isApiError } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { Field, Input } from '@/components/ui/Form';
import { ThemeToggle } from '@/components/ui/ThemeToggle';
import { Spinner } from '@/components/ui/Card';
import { BrandMark } from '@/components/ui/Brand';
import { cn } from '@/lib/cn';

type Mode = 'login' | 'register';

export function LoginPage() {
  const { user, loading, setUser } = useAuth();
  const [mode, setMode] = useState<Mode>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center bg-canvas">
        <Spinner className="h-5 w-5 text-primary" />
      </div>
    );
  }

  if (user) return <Navigate to="/" replace />;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result =
        mode === 'login'
          ? await api.login(username, password)
          : await api.register(username, password, displayName);
      setUser(result.user);
    } catch (caught) {
      setError(isApiError(caught) ? caught.detail : '操作失败');
    } finally {
      setBusy(false);
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  return (
    <div className="relative grid min-h-screen place-items-center px-6 py-10">
      <div className="absolute right-6 top-6 z-10">
        <ThemeToggle />
      </div>

      <div className="relative w-full max-w-[680px] animate-rise">
        <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-overlay md:grid md:grid-cols-[248px_1fr]">
          <div className="relative flex flex-col justify-center gap-6 border-b border-line bg-sunken px-8 py-10 md:border-b-0 md:border-r">
            <BrandMark size={54} />
            <div>
              <h1 className="text-[28px] font-extrabold leading-none tracking-[0.02em] text-ink">
                墨卷
              </h1>
              <p className="mt-4 text-[12.5px] leading-relaxed text-ink-faint">
                把散落的题目收进一卷，
                <br />
                再一题题做完它。
              </p>
            </div>
          </div>

          <div className="p-8">
            <div className="mb-6 flex gap-6 border-b border-line-soft">
              {(['login', 'register'] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => switchMode(item)}
                  className={cn(
                    'focus-ring -mb-px border-b-2 pb-2.5 text-[14px] transition-colors duration-200',
                    mode === item
                      ? 'border-primary text-ink'
                      : 'border-transparent text-ink-faint hover:text-ink-muted',
                  )}
                >
                  {item === 'login' ? '登录' : '注册'}
                </button>
              ))}
            </div>

            <form onSubmit={handleSubmit} className="stagger space-y-4">
              <Field label="用户名">
                <Input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="username"
                  autoFocus
                />
              </Field>

              {mode === 'register' ? (
                <Field label="昵称">
                  <Input
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    placeholder="可留空"
                  />
                </Field>
              ) : null}

              <Field label="密码">
                <Input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                />
              </Field>

              {error ? (
                <p className="animate-rise rounded-md border border-danger/25 bg-danger/10 px-3 py-2 text-[13px] text-danger-deep">
                  {error}
                </p>
              ) : null}

              <Button
                type="submit"
                variant="primary"
                size="lg"
                loading={busy}
                className="w-full"
              >
                {busy ? null : mode === 'login' ? '登录' : '注册并进入'}
              </Button>
            </form>
          </div>
        </div>

        <p className="mt-5 text-center text-[12px] text-ink-faint/70">
          局域网自部署 · 数据留在本机
        </p>
      </div>
    </div>
  );
}

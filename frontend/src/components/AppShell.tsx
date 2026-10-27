import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '@/auth';
import { NAV_ITEMS } from '@/components/nav-config';
import { ThemeToggle } from '@/components/ui/ThemeToggle';
import { Avatar, BrandMark } from '@/components/ui/Brand';
import { IconLogout, IconSearch } from '@/components/ui/icons';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';

/** 浮动芯片的公共外观：胶囊 + 毛玻璃 + 柔和阴影 */
const chipClass =
  'flex items-center gap-2.5 rounded-full border border-line bg-surface/85 px-3.5 py-[7px] shadow-lifted backdrop-blur-xl';
const chipIconClass =
  'grid h-9 w-9 place-items-center rounded-full border border-line bg-surface/85 text-ink-muted shadow-paper backdrop-blur-xl transition-colors hover:text-ink';

const WideContentContext = createContext<(next: boolean) => void>(() => {});

/**
 * 页面申请放宽内容区：默认 1200px 在大屏上两侧空得慌，
 * 网格态（题库 / 刷题 / 考试 / 结算）切到 1600px 好把多出来的空间换成多一列。
 * 列表态仍然回到 1200px——单列摊太宽不好读。
 */
export function useWideContent(enabled: boolean) {
  const request = useContext(WideContentContext);
  useEffect(() => {
    request(enabled);
    return () => request(false);
  }, [enabled, request]);
}

export function AppShell() {
  const { user, setUser } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [wide, setWide] = useState(false);
  const requestWide = useCallback((next: boolean) => setWide(next), []);

  async function handleLogout() {
    try {
      await api.logout();
    } catch {
      /* 无论后端是否成功，前端都切回未登录态 */
    }
    setUser(null);
  }

  function handleSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = new FormData(event.currentTarget).get('q');
    const keyword = typeof q === 'string' ? q.trim() : '';
    navigate(keyword ? `/bank?q=${encodeURIComponent(keyword)}` : '/bank');
  }

  return (
    <div className="min-h-screen">
      {/* 左上：品牌芯片 */}
      <div className="fixed left-[18px] top-4 z-40">
        <Link to="/" className={cn(chipClass, 'focus-ring group')} title="墨卷 · 返回概览">
          <BrandMark size={28} />
          <b className="text-[14.5px] font-bold tracking-[0.02em] text-ink">墨卷</b>
        </Link>
      </div>

      {/* 右上：搜索 · 日夜 · 头像 · 退出 */}
      <div className="fixed right-[18px] top-4 z-40 flex items-center gap-2.5">
        <form
          onSubmit={handleSearch}
          className={cn(chipClass, 'hidden text-ink-faint md:flex')}
          role="search"
        >
          <IconSearch className="h-4 w-4" />
          <input
            name="q"
            placeholder="搜题目，回车进题库"
            aria-label="搜索题目"
            className="w-[150px] bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-faint"
          />
        </form>

        <ThemeToggle />

        <div className={cn(chipClass, 'hidden !px-[5px] !py-[5px] md:flex')}>
          <Avatar name={user?.displayName || '我'} size={26} />
          <span className="max-w-[110px] truncate px-1.5 text-[13px] font-medium text-ink">
            {user?.displayName}
          </span>
        </div>

        <button
          type="button"
          title="退出登录"
          aria-label="退出登录"
          onClick={handleLogout}
          className={cn(chipIconClass, 'focus-ring hover:text-danger')}
        >
          <IconLogout className="h-4 w-4" />
        </button>
      </div>

      {/* 底部悬浮 Dock：游戏底舱式导航 */}
      <nav
        aria-label="主导航"
        className="fixed bottom-[18px] left-1/2 z-50 flex max-w-[calc(100vw-24px)] -translate-x-1/2 items-center gap-0.5 overflow-x-auto rounded-full border border-line bg-surface/85 p-1.5 shadow-overlay backdrop-blur-xl"
      >
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return item.href ? (
            <NavLink
              key={item.label}
              to={item.href}
              end={item.href === '/'}
              title={item.hint}
              className={({ isActive }) =>
                cn(
                  'focus-ring relative flex shrink-0 flex-col items-center gap-[3px] rounded-full px-3 pb-[5px] pt-[6px] text-[11px] font-semibold transition-colors duration-150 sm:px-[15px]',
                  isActive
                    ? 'bg-primary/10 text-primary-text'
                    : 'text-ink-muted hover:bg-surface-raised hover:text-ink',
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive ? (
                    <span
                      className="absolute top-[3px] left-1/2 h-1 w-1 -translate-x-1/2 rounded-full bg-primary"
                      aria-hidden="true"
                    />
                  ) : null}
                  {Icon ? <Icon className="h-[21px] w-[21px]" /> : null}
                  <span className="hidden sm:inline">{item.label}</span>
                </>
              )}
            </NavLink>
          ) : (
            <span
              key={item.label}
              title="尚未实现"
              className="shrink-0 cursor-not-allowed rounded-full px-3 pb-[5px] pt-[6px] text-[11px] font-semibold text-ink-faint/50"
            >
              {item.label}
            </span>
          );
        })}
      </nav>

      <main className={cn('mx-auto px-5 pb-[120px] pt-[76px]', wide ? 'max-w-wide' : 'max-w-work')}>
        {/* 换路由时整段浮起一次，路径变化即重挂载 */}
        <div key={location.pathname} className="animate-rise">
          <WideContentContext.Provider value={requestWide}>
            <Outlet />
          </WideContentContext.Provider>
        </div>
      </main>
    </div>
  );
}

export function PageTitle({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex items-end justify-between gap-6">
      <div className="min-w-0">
        <h1 className="text-[22px] font-extrabold leading-tight tracking-[-0.01em] text-ink">
          {title}
        </h1>
        {subtitle ? (
          <p className="mt-1.5 text-[13px] leading-relaxed text-ink-muted">{subtitle}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0 pb-0.5">{action}</div> : null}
    </div>
  );
}

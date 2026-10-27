import { useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

/**
 * 把浮层挂到 body 上。
 *
 * 页面容器带 `animate-rise`（keyframes 里有 transform，且 fill-mode 为 both），
 * 会让它成为 `position: fixed` 的包含块——浮层于是相对整页居中而不是相对视口，
 * 页面一滚就跑到看不见的地方。挂到 body 才真正贴着屏幕。
 */
export function Portal({ children }: { children: ReactNode }) {
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  return createPortal(children, document.body);
}

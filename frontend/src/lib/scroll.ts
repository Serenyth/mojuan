/** 翻阅式答题的滚动定位：尊重系统「减少动态效果」设置。 */

export function scrollToElement(node: HTMLElement | null | undefined): void {
  if (!node) return;
  let reduce = false;
  try {
    reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    /* matchMedia 不可用（老浏览器 / 测试桩）时按不减少处理 */
  }
  node.scrollIntoView?.({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
}

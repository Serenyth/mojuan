import { cn } from '@/lib/cn';

/*
 * 品牌方块与头像。渐变是品牌识别的一部分，两个主题同一组值，
 * 所以这里写死而不用语义色令牌（语义色管界面状态，不管品牌 identity）。
 */

const BRAND_GRADIENT = 'linear-gradient(135deg, #7a5af8, #5b3df5)';
const BRAND_SHADOW = '0 3px 10px -2px rgba(91, 61, 245, 0.45)';
const AVATAR_GRADIENT = 'linear-gradient(135deg, #a5b4fc, #818cf8)';

export function BrandMark({
  size = 30,
  char = '墨',
  className,
}: {
  size?: number;
  char?: string;
  className?: string;
}) {
  return (
    <span
      className={cn('grid shrink-0 place-items-center rounded-[10px] font-bold text-white', className)}
      style={{
        width: size,
        height: size,
        background: BRAND_GRADIENT,
        boxShadow: BRAND_SHADOW,
        fontSize: Math.round(size * 0.5),
      }}
      aria-hidden="true"
    >
      {char}
    </span>
  );
}

export function Avatar({
  name,
  size = 30,
  className,
}: {
  name: string;
  size?: number;
  className?: string;
}) {
  const initial = name.trim().charAt(0).toUpperCase() || '?';
  return (
    <span
      className={cn('grid shrink-0 place-items-center rounded-full font-bold text-white', className)}
      style={{
        width: size,
        height: size,
        background: AVATAR_GRADIENT,
        fontSize: Math.round(size * 0.4),
      }}
      title={name}
    >
      {initial}
    </span>
  );
}

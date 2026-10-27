import type { SVGProps } from 'react';
import { cn } from '@/lib/cn';

/*
 * 线性图标集：24 视窗、1.8 描边、圆角线帽，与「桌面工作台」的轻量质感对齐。
 * 用法：<IconGrid className="h-4 w-4" />，尺寸用 className 覆盖，颜色随 currentColor。
 */

type IconProps = SVGProps<SVGSVGElement>;

function Svg({ className, children, ...rest }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn('h-5 w-5 shrink-0', className)}
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconGrid = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="3" width="7.5" height="7.5" rx="2" />
    <rect x="13.5" y="3" width="7.5" height="7.5" rx="2" />
    <rect x="3" y="13.5" width="7.5" height="7.5" rx="2" />
    <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2" />
  </Svg>
);

export const IconInbox = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 12h5l2 3h4l2-3h5" />
    <path d="M5.5 4h13l2.5 8.5V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5.5z" />
  </Svg>
);

export const IconLibrary = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
  </Svg>
);

export const IconPlay = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M10 8.6l6 3.4-6 3.4z" />
  </Svg>
);

export const IconAward = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="9" r="6" />
    <path d="M8.8 14.2L7 22l5-2.8L17 22l-1.8-7.8" />
  </Svg>
);

export const IconSliders = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 21v-6M4 11V3M12 21v-9M12 8V3M20 21v-4M20 13V3" />
    <path d="M1.8 15h4.4M9.8 8h4.4M17.8 17h4.4" />
  </Svg>
);

export const IconSearch = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-3.6-3.6" />
  </Svg>
);

export const IconBell = (p: IconProps) => (
  <Svg {...p}>
    <path d="M18 8.5a6 6 0 1 0-12 0c0 6.5-2.5 7.5-2.5 7.5h17S18 15 18 8.5" />
    <path d="M13.7 20.5a2 2 0 0 1-3.4 0" />
  </Svg>
);

export const IconCheck = (p: IconProps) => (
  <Svg {...p} strokeWidth={2.4}>
    <path d="M20 6.5L9.5 17 4 11.5" />
  </Svg>
);

export const IconX = (p: IconProps) => (
  <Svg {...p} strokeWidth={2.2}>
    <path d="M18 6L6 18M6 6l12 12" />
  </Svg>
);

export const IconClock = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7.5V12l3 2" />
  </Svg>
);

export const IconFlame = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 22c4 0 6.8-2.8 6.8-6.6 0-4.8-4-6.8-4-10.4 0 0-3.4 1.8-3.4 5.2 0-1.6-1.8-3.2-1.8-3.2C7 9 5.2 11.2 5.2 13.6 5.2 19.2 8 22 12 22z" />
  </Svg>
);

export const IconTarget = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <circle cx="12" cy="12" r="5" />
    <circle cx="12" cy="12" r="1.4" fill="currentColor" />
  </Svg>
);

export const IconTag = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20.6 13.4L11 3.8A2 2 0 0 0 9.6 3H4v5.6a2 2 0 0 0 .6 1.4l9.6 9.6a2 2 0 0 0 2.8 0l3.6-3.6a2 2 0 0 0 0-2.6z" />
    <circle cx="7.6" cy="7.6" r="1.4" fill="currentColor" />
  </Svg>
);

export const IconSparkles = (p: IconProps) => (
  <Svg {...p}>
    <path d="M11 3l1.7 4.4L17 9.1l-4.3 1.7L11 15.2 9.3 10.8 5 9.1l4.3-1.7z" />
    <path d="M18 14.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z" />
  </Svg>
);

export const IconFile = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14 2.5H6.5A2 2 0 0 0 4.5 4.5v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8z" />
    <path d="M14 2.5V8h5.5" />
    <path d="M8.5 13h7M8.5 16.5h5" />
  </Svg>
);

export const IconEdit = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 20.5h9" />
    <path d="M16.5 3.8a2.1 2.1 0 0 1 3 3L7.5 18.8 3 20.2l1.4-4.5z" />
  </Svg>
);

export const IconList = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 6h11M9 12h11M9 18h11" />
    <path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01" />
  </Svg>
);

export const IconBraces = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 3c-1.7 0-3 1.6-3 3.5V9c0 1-.7 1.5-1.3 2.3C3.1 12 4 12.7 4 14v2.5C4 18.4 5.3 20 7 20" />
    <path d="M16 3c1.7 0 3 1.6 3 3.5V9c0 1 .7 1.5 1.3 2.3.6.7-.3 1.4-.3 2.7v2.5c0 1.9-1.3 3.5-3 3.5" />
  </Svg>
);

export const IconTrash = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 6.5h17M9 6.5V4h6v2.5" />
    <path d="M18.5 6.5l-1 14h-11l-1-14" />
    <path d="M10 11v5.5M14 11v5.5" />
  </Svg>
);

export const IconPlus = (p: IconProps) => (
  <Svg {...p} strokeWidth={2}>
    <path d="M12 5.5v13M5.5 12h13" />
  </Svg>
);

export const IconEye = (p: IconProps) => (
  <Svg {...p}>
    <path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12z" />
    <circle cx="12" cy="12" r="3" />
  </Svg>
);

export const IconArrow = (p: IconProps) => (
  <Svg {...p} strokeWidth={2}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Svg>
);

export const IconRefresh = (p: IconProps) => (
  <Svg {...p}>
    <path d="M21 12a9 9 0 1 1-2.6-6.4" />
    <path d="M21 3.5V9h-5.5" />
  </Svg>
);

export const IconChevron = (p: IconProps) => (
  <Svg {...p} strokeWidth={2}>
    <path d="M6 9.5l6 6 6-6" />
  </Svg>
);

export const IconZap = (p: IconProps) => (
  <Svg {...p}>
    <path d="M13 2.5L4.5 14H10l-1 7.5L18.5 10H13z" />
  </Svg>
);

export const IconUsers = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="9" cy="8" r="3.8" />
    <path d="M2.5 20.5c0-3.8 2.9-6 6.5-6s6.5 2.2 6.5 6" />
    <path d="M16 4.6a3.8 3.8 0 0 1 0 7.2" />
    <path d="M17.8 14.9c2.2.8 3.7 2.7 3.7 5.6" />
  </Svg>
);

export const IconSun = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4.2" />
    <path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7" />
  </Svg>
);

export const IconMoon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20.2 14.2A8.6 8.6 0 0 1 9.8 3.8 8.6 8.6 0 1 0 20.2 14.2z" />
  </Svg>
);

export const IconImage = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="3" width="18" height="18" rx="2.5" />
    <circle cx="8.5" cy="8.5" r="1.6" />
    <path d="M20.5 15.5L15 10l-9.5 10" />
  </Svg>
);

export const IconLink = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10.5 13.5a5 5 0 0 0 7.1 0l2.8-2.8a5 5 0 0 0-7.1-7.1l-1.4 1.4" />
    <path d="M13.5 10.5a5 5 0 0 0-7.1 0L3.6 13.3a5 5 0 0 0 7.1 7.1l1.4-1.4" />
  </Svg>
);

export const IconUpload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 16V4.5" />
    <path d="M6.5 10L12 4.5 17.5 10" />
    <path d="M4 15v3.5A2 2 0 0 0 6 20.5h12a2 2 0 0 0 2-2.5V15" />
  </Svg>
);

export const IconChart = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20V11M10 20V4M16 20v-6M22 20H2" />
  </Svg>
);

export const IconLogout = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 21H5.5A2.5 2.5 0 0 1 3 18.5v-13A2.5 2.5 0 0 1 5.5 3H9" />
    <path d="M16 17l5-5-5-5" />
    <path d="M21 12H9" />
  </Svg>
);

export const IconCode = (p: IconProps) => (
  <Svg {...p}>
    <path d="m8 7-5 5 5 5" />
    <path d="m16 7 5 5-5 5" />
    <path d="m13.5 5-3 14" />
  </Svg>
);

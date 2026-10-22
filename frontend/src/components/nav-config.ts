import type { ComponentType, SVGProps } from 'react';
import {
  IconAward,
  IconGrid,
  IconInbox,
  IconLibrary,
  IconPlay,
  IconSliders,
} from '@/components/ui/icons';

export interface NavItem {
  label: string;
  href?: string;
  hint?: string;
  icon?: ComponentType<SVGProps<SVGSVGElement>>;
}

/** 未填 href 的板块尚未落地页面，落地后补上 href 即可启用 */
export const NAV_ITEMS: NavItem[] = [
  { label: '概览', href: '/', icon: IconGrid, hint: '今日进度与全局状态' },
  { label: '题库', href: '/bank', icon: IconLibrary, hint: '全部题目' },
  { label: '导入', href: '/import', icon: IconInbox, hint: 'AI 提取与脚本' },
  { label: '刷题', href: '/practice', icon: IconPlay, hint: '开始练习' },
  { label: '考试', href: '/exam', icon: IconAward, hint: '选试卷开考' },
  { label: '设置', href: '/settings', icon: IconSliders, hint: '账号与判分' },
];

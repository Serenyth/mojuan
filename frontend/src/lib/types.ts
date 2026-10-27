export type QuestionType =
  | 'single_choice'
  | 'multiple_choice'
  | 'true_false'
  | 'fill_blank'
  | 'subjective';

export interface User {
  id: string;
  username: string;
  displayName: string;
  isAdmin: boolean;
}

export interface Settings {
  ai_base_url: string;
  ai_api_key: string;
  ai_api_key_configured: string;
  ai_model: string;
  ai_vision_model: string;
  multiple_partial_credit: string;
  multiple_partial_ratio: string;
  fill_ignore_case: string;
  subjective_max_score: string;
  subjective_pass_ratio: string;
  master_streak: string;
  /** 导入助手（AI 对话）的系统提示词：当前实际生效值 */
  agent_system_prompt: string;
  /** 内置默认提示词（用于「恢复默认」与判断是否默认） */
  agent_system_prompt_default: string;
  /** 'true' / 'false'：当前是否就是内置默认 */
  agent_system_prompt_is_default: string;
}

/** 阶段四：可复用提取脚本 */
export interface ExtractionScript {
  id: string;
  name: string;
  platform: string;
  code: string;
  version: number;
  ioSpec: unknown;
  ownerId: string | null;
  isShared: boolean;
  createdAt: string;
  canEdit: boolean;
}

export interface SettingsResponse {
  settings: Settings;
  isAdmin: boolean;
}

export interface LoginResult {
  ok: boolean;
  user: User;
}

export interface MeResult {
  user: User;
}

export interface Option {
  key: string;
  text: string;
}

export interface Question {
  id: string;
  bankId: string;
  type: QuestionType;
  content: string;
  options: Option[] | null;
  answer: unknown;
  acceptableAnswers?: string[][];
  explanation: string | null;
  tags: string[];
  difficulty: number;
  confidence: number;
  fingerprint?: string;
  createdAt: string;
}

export const QUESTION_TYPE_LABEL: Record<QuestionType, string> = {
  single_choice: '单选',
  multiple_choice: '多选',
  true_false: '判断',
  fill_blank: '填空',
  subjective: '主观',
};

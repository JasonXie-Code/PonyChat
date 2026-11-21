/**
 * 各变体（MLP / Standard）站点级文案与行为，由变体目录下 config.ts 提供。
 */
export interface SiteConfig {
  storageKey: string;
  anonIdKey: string;
  /** 顶栏「当前站」链接文案 */
  headerNavMbtiLabel: string;
  /** 页脚说明 */
  footerNote: string;
  introHeading: string;
  /** 首段加粗关键词 */
  introP1Bold: string;
  /** 首段加粗后的其余句子 */
  introP1Rest: string;
  introP2: string;
  introP3: string;
  wikiHeading: string;
  wikiSubtitle: string;
  wikiLinkText: string;
  /** 结果/预览中「典型小马：」「典型人物：」等前缀 */
  typicalLabel: string;
  /** TypeExplanation 无 profile 时的提示 */
  typeExplanationEmptyHint: string;
  /** 「四个字母/四个维度分别代表什么」 */
  typeExplanationSubHeading: string;
}

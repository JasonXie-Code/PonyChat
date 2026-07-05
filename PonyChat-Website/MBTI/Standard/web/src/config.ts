import type { SiteConfig } from "@common/config/types";

const config: SiteConfig = {
  storageKey: "standard_mbti_session_v1",
  anonIdKey: "standard_mbti_anon_id",
  headerNavMbtiLabel: "MBTI测试",
  footerNote:
    "标准人格类型倾向自测，非临床测评；结果与作答仅存本机浏览器。",
  introHeading: "欢迎来到标准人格类型测验",
  introP1Bold: "迈尔斯-布里格斯类型指标",
  introP1Rest: "从四个维度描述偏好，组合为十六种人格类型编码。",
  introP2:
    "本站为标准情境自测，非官方、非临床测评；结果供自我了解与职业规划参考，请勿替代专业心理评估。",
  introP3:
    "题库 72 题，每次随机抽取 12 或 36 题。匿名编号与作答保存在本机浏览器，不上传服务器。",
  wikiHeading: "人格类型百科",
  wikiSubtitle: "人物与类型的对应为常见归纳参考，非学术背书。",
  wikiLinkText: "查看人格类型百科",
  typicalLabel: "典型人物：",
  typeExplanationEmptyHint: "暂无该类型的详细文案，各维度含义见下表。",
  typeExplanationSubHeading: "四个维度分别代表什么",
};

export default config;

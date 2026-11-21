import type { SiteConfig } from "@common/config/types";

const config: SiteConfig = {
  storageKey: "mlp_mbti_session_v1",
  anonIdKey: "mlp_mbti_anon_id",
  headerNavMbtiLabel: "MBTI测试",
  footerNote: "MBTI 同人娱乐测验，非临床测评；结果与作答仅存本机浏览器。",
  introHeading: "欢迎来到 MLP MBTI",
  introP1Bold: "MBTI",
  introP1Rest:
    "（迈尔斯-布里格斯类型指标）从四个维度描述偏好，组合为 16 种四字母类型。",
  introP2:
    "本站为小马情境同人测试，非官方、非临床测评；结果供交流参考。",
  introP3:
    "题库 72 题，每次随机抽取 12 或 36 题。匿名编号与作答保存在本机浏览器，不上传服务器。",
  wikiHeading: "小马 MBTI 百科",
  wikiSubtitle: "角色与类型的对应为同人参考。",
  wikiLinkText: "查看小马 MBTI 百科",
  typicalLabel: "典型小马：",
  typeExplanationEmptyHint: "暂无该类型的详细文案，四字母含义见下表。",
  typeExplanationSubHeading: "四个字母分别代表什么",
};

export default config;

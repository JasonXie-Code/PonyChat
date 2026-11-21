/**
 * 十六型通用中文简称（与 Standard 站 typeProfiles.nickname 在「（」前一致）。
 * 两站结果标题、友伴类型行等统一使用，不随 MLP 马设昵称变化。
 */
export const MBTI_STANDARD_SHORT_ZH: Record<string, string> = {
  INTJ: "建筑师型",
  INTP: "思想家型",
  ENTJ: "指挥官型",
  ENTP: "辩论家型",
  INFJ: "提倡者型",
  INFP: "调停者型",
  ENFJ: "主人公型",
  ENFP: "竞选者型",
  ISTJ: "物流师型",
  ISFJ: "守卫者型",
  ESTJ: "总经理型",
  ESFJ: "执政官型",
  ISTP: "鉴赏家型",
  ISFP: "探险家型",
  ESTP: "企业家型",
  ESFP: "表演者型",
};

export function standardShortZh(code: string): string {
  const k = code.toUpperCase();
  return MBTI_STANDARD_SHORT_ZH[k] ?? k;
}

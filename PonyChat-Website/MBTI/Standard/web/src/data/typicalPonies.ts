/**
 * 四字母类型 → 典型代表人物（常见文化/学术归纳，仅供自测参考，非临床标签）。
 * 伴侣行按性别取相反侧：ponyForPartner。
 */

export const typicalPonyByType: Record<string, string> = {
  INTJ: "艾萨克·牛顿",
  INTP: "阿尔伯特·爱因斯坦",
  ENTJ: "史蒂夫·乔布斯",
  ENTP: "本杰明·富兰克林",
  INFJ: "马丁·路德·金",
  INFP: "威廉·莎士比亚",
  ENFJ: "奥普拉·温弗瑞",
  ENFP: "罗宾·威廉姆斯",
  ISTJ: "安格拉·默克尔",
  ISFJ: "特蕾莎修女",
  ESTJ: "亨利·福特",
  ESFJ: "泰勒·斯威夫特",
  ISTP: "克林特·伊斯特伍德",
  ISFP: "迈克尔·杰克逊",
  ESTP: "欧内斯特·海明威",
  ESFP: "玛丽莲·梦露",
};

/** 各类型各性别一条代表（伴侣行：取与用户性别相反的一侧） */
export const ponyByTypeSex: Record<string, { male: string; female: string }> = {
  INTJ: { male: "埃隆·马斯克", female: "艾萨克·牛顿" },
  INTP: { male: "比尔·盖茨", female: "玛丽·居里" },
  ENTJ: { male: "史蒂夫·乔布斯", female: "玛格丽特·撒切尔" },
  ENTP: { male: "本杰明·富兰克林", female: "凯瑟琳·赫本" },
  INFJ: { male: "纳尔逊·曼德拉", female: "嘎嘎小姐" },
  INFP: { male: "约翰·列侬", female: "奥黛丽·赫本" },
  ENFJ: { male: "贝拉克·奥巴马", female: "奥普拉·温弗瑞" },
  ENFP: { male: "罗宾·威廉姆斯", female: "艾伦·德杰尼勒斯" },
  ISTJ: { male: "乔治·华盛顿", female: "安格拉·默克尔" },
  ISFJ: { male: "弗雷德·罗杰斯", female: "凯特·米德尔顿" },
  ESTJ: { male: "亨利·福特", female: "希拉里·克林顿" },
  ESFJ: { male: "休·杰克曼", female: "泰勒·斯威夫特" },
  ISTP: { male: "克林特·伊斯特伍德", female: "阿米莉亚·埃尔哈特" },
  ISFP: { male: "迈克尔·杰克逊", female: "布兰妮·斯皮尔斯" },
  ESTP: { male: "欧内斯特·海明威", female: "麦当娜" },
  ESFP: { male: "威尔·史密斯", female: "玛丽莲·梦露" },
};

export type GenderKind = "male" | "female" | "unknown";

/** 根据用户填写的性别文案判断男/女（无法识别则为 unknown） */
export function normalizeGender(input: string): GenderKind {
  const s = input.trim().toLowerCase();
  if (!s) return "unknown";
  if (/男|^(m|male)$/.test(s) || s === "他") return "male";
  if (/女|^(f|female)$/.test(s) || s === "她") return "female";
  return "unknown";
}

export function ponyFor(type: string): string {
  return typicalPonyByType[type] ?? "（待收录）";
}

/**
 * 伴侣推荐对应的典型人物：与界面规则一致取性别相反一侧；无法识别性别时默认取女性向名单。
 */
export function ponyForPartner(partnerType: string, userGender: string): string {
  const code = partnerType.toUpperCase();
  const pair = ponyByTypeSex[code];
  if (!pair) return ponyFor(code);
  const g = normalizeGender(userGender);
  if (g === "female") return pair.male;
  if (g === "male") return pair.female;
  return pair.female;
}

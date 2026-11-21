/**
 * 四字母类型 → 典型小马名称（优先 M6 与主线高辨识度角色）。
 * 伴侣向展示需与用户性别相反：`ponyForPartner`。
 */

export const typicalPonyByType: Record<string, string> = {
  INTJ: "紫悦",
  INTP: "星光熠熠",
  ENTJ: "宇宙公主",
  ENTP: "无序",
  INFJ: "月亮公主",
  INFP: "柔柔",
  ENFJ: "韵律公主",
  ENFP: "碧琪",
  ISTJ: "苹果嘉儿",
  ISFJ: "甜心宝宝",
  ESTJ: "史密夫婆婆",
  ESFJ: "珍奇",
  ISTP: "闪尘",
  ISFP: "可可·帕梅尔",
  ESTP: "云宝",
  ESFP: "吉尔达",
};

/** 各类型各性别一条代表角色（伴侣行：取与用户性别相反的一侧） */
export const ponyByTypeSex: Record<string, { male: string; female: string }> = {
  INTJ: { male: "银甲闪闪", female: "紫悦" },
  INTP: { male: "隙日", female: "星光熠熠" },
  ENTJ: { male: "黑晶王", female: "宇宙公主" },
  ENTP: { male: "无序", female: "崔克茜" },
  INFJ: { male: "星璇", female: "月亮公主" },
  INFP: { male: "大麦", female: "柔柔" },
  ENFJ: { male: "银甲闪闪", female: "韵律公主" },
  ENFP: { male: "芝士三明治", female: "碧琪" },
  ISTJ: { male: "麦托什", female: "苹果嘉儿" },
  ISFJ: { male: "斯派克", female: "甜心宝宝" },
  ESTJ: { male: "蓝血王子", female: "史密夫婆婆" },
  ESFJ: { male: "芝士三明治", female: "珍奇" },
  ISTP: { male: "阿绅", female: "闪尘" },
  ISFP: { male: "大麦", female: "可可·帕梅尔" },
  ESTP: { male: "雷鸣", female: "云宝" },
  ESFP: { male: "芝士三明治", female: "吉尔达" },
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
 * 伴侣推荐对应的典型小马：必须与用户自称性别相反；无法识别性别时默认取女性向名单。
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

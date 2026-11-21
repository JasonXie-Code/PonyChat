export interface WikiEntry {
  id: string;
  name: string;
  mbti: string;
  blurb: string;
}

/** 百科静态条目 */
export const wikiEntries: WikiEntry[] = [
  {
    id: "twilight",
    name: "紫悦",
    mbti: "INTJ",
    blurb: "爱书、爱计划，友谊与魔法的研究者。",
  },
  {
    id: "pinkie",
    name: "碧琪",
    mbti: "ENFP",
    blurb: "派对与惊喜的化身，外向直觉与情感驱动。",
  },
  {
    id: "rarity",
    name: "珍奇",
    mbti: "ESFJ",
    blurb: "注重美感与社交氛围，体贴与表达并存。",
  },
  {
    id: "dash",
    name: "云宝",
    mbti: "ESTP",
    blurb: "行动派、竞技与即兴，享受当下挑战。",
  },
  {
    id: "fluttershy",
    name: "柔柔",
    mbti: "INFP",
    blurb: "温柔内敛，重视内心价值与和谐。",
  },
  {
    id: "applejack",
    name: "苹果嘉儿",
    mbti: "ISTJ",
    blurb: "踏实可靠，重视责任与传统。",
  },
];

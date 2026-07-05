export interface WikiEntry {
  id: string;
  name: string;
  mbti: string;
  blurb: string;
}

/** 百科静态条目（常见文化归纳，非学术诊断） */
export const wikiEntries: WikiEntry[] = [
  {
    id: "newton",
    name: "艾萨克·牛顿",
    mbti: "建筑师型",
    blurb: "体系化与自然哲学；长期专注、独立推演，常被视为建筑师型人格的典型归纳。",
  },
  {
    id: "oprah",
    name: "奥普拉·温弗瑞",
    mbti: "主人公型",
    blurb: "访谈、公益与公众叙事；关注成长与连结，常被视为主人公型人格的典型归纳。",
  },
  {
    id: "swift",
    name: "泰勒·斯威夫特",
    mbti: "执政官型",
    blurb: "作品与公众形象中的叙事、仪式感与受众连结，常被视为执政官型人格的典型归纳。",
  },
  {
    id: "hemingway",
    name: "欧内斯特·海明威",
    mbti: "企业家型",
    blurb: "行动、冒险与简洁叙事；临场感强，常被视为企业家型人格的典型归纳。",
  },
  {
    id: "shakespeare",
    name: "威廉·莎士比亚",
    mbti: "调停者型",
    blurb: "人物内心与价值冲突的刻画；内向情感与语言创造，常被视为调停者型人格的典型归纳。",
  },
  {
    id: "merkel",
    name: "安格拉·默克尔",
    mbti: "物流师型",
    blurb: "稳健、程序与可预期性；长期执政中的责任与规范，常被视为物流师型人格的典型归纳。",
  },
];

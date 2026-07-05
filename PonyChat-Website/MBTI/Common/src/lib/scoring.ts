import type { QuestionBank, QuestionItem, Side } from "./types";

/** 平局规则与 docs/SCORING.md 一致 */
const TIE: Record<QuestionItem["axis"], string> = {
  EI: "I",
  SN: "N",
  TF: "F",
  JP: "P",
};

function axisLetter(
  axis: QuestionItem["axis"],
  leftScore: number,
  rightScore: number,
  leftLetter: string,
  rightLetter: string
): string {
  if (leftScore > rightScore) return leftLetter;
  if (rightScore > leftScore) return rightLetter;
  return TIE[axis];
}

export interface AxisCounts {
  left: number;
  right: number;
}

export interface AxisSpectrumRow {
  axis: QuestionItem["axis"];
  title: string;
  leftLetter: string;
  rightLetter: string;
  left: number;
  right: number;
  /** 左端字母一侧得分占比 0–100，50 表示两侧持平（中间带） */
  leftPercent: number;
  /** 本次判定字母（与平局规则一致） */
  letter: string;
}

const AXIS_META: Record<
  QuestionItem["axis"],
  { title: string; leftLetter: string; rightLetter: string }
> = {
  EI: { title: "能量来源", leftLetter: "E", rightLetter: "I" },
  SN: { title: "信息方式", leftLetter: "S", rightLetter: "N" },
  TF: { title: "决策依据", leftLetter: "T", rightLetter: "F" },
  JP: { title: "生活方式", leftLetter: "J", rightLetter: "P" },
};

/** 四轴原始计数（左选项 / 右选项各计一票） */
export function collectAxisCounts(
  bank: QuestionBank,
  activeIds: Iterable<number>,
  answers: Record<number, Side>
): Record<QuestionItem["axis"], AxisCounts> {
  const ids = new Set(activeIds);
  const out: Record<QuestionItem["axis"], AxisCounts> = {
    EI: { left: 0, right: 0 },
    SN: { left: 0, right: 0 },
    TF: { left: 0, right: 0 },
    JP: { left: 0, right: 0 },
  };

  for (const item of bank.items) {
    if (!ids.has(item.id)) continue;
    const a = answers[item.id];
    if (!a) continue;
    const left = a === "L";
    const bucket = out[item.axis];
    if (left) bucket.left += 1;
    else bucket.right += 1;
  }
  return out;
}

/** 四轴光谱：用于结果页分布条 */
export function axisSpectra(
  bank: QuestionBank,
  activeIds: Iterable<number>,
  answers: Record<number, Side>
): AxisSpectrumRow[] {
  const counts = collectAxisCounts(bank, activeIds, answers);
  const order: QuestionItem["axis"][] = ["EI", "SN", "TF", "JP"];
  return order.map((axis) => {
    const { left, right } = counts[axis];
    const total = left + right;
    const leftPercent =
      total === 0 ? 50 : Math.round((left / total) * 1000) / 10;
    const meta = AXIS_META[axis];
    const letter = axisLetter(
      axis,
      left,
      right,
      meta.leftLetter,
      meta.rightLetter
    );
    return {
      axis,
      title: meta.title,
      leftLetter: meta.leftLetter,
      rightLetter: meta.rightLetter,
      left,
      right,
      leftPercent,
      letter,
    };
  });
}

/** 仅根据本次测验实际出现的题号 `activeIds` 计分 */
export function scoreMbti(
  bank: QuestionBank,
  activeIds: Iterable<number>,
  answers: Record<number, Side>
): string {
  const c = collectAxisCounts(bank, activeIds, answers);
  const first = axisLetter("EI", c.EI.left, c.EI.right, "E", "I");
  const second = axisLetter("SN", c.SN.left, c.SN.right, "S", "N");
  const third = axisLetter("TF", c.TF.left, c.TF.right, "T", "F");
  const fourth = axisLetter("JP", c.JP.left, c.JP.right, "J", "P");
  return `${first}${second}${third}${fourth}`;
}

/** 友伴推荐：朋友 = 仅翻转 E/I；伴侣 = 仅翻转 J/P */
export function recommendFriendPartner(mbti: string): {
  friendType: string;
  partnerType: string;
} {
  const [a, b, c, d] = mbti.split("");
  const friendType = `${a === "E" ? "I" : "E"}${b}${c}${d}`;
  const partnerType = `${a}${b}${c}${d === "J" ? "P" : "J"}`;
  return { friendType, partnerType };
}

/** 16 型四字母列表（用于浏览页） */
export const MBTI_TYPES_16 = [
  "INTJ",
  "INTP",
  "ENTJ",
  "ENTP",
  "INFJ",
  "INFP",
  "ENFJ",
  "ENFP",
  "ISTJ",
  "ISFJ",
  "ESTJ",
  "ESFJ",
  "ISTP",
  "ISFP",
  "ESTP",
  "ESFP",
] as const;

export type Mbti16Code = (typeof MBTI_TYPES_16)[number];

export function isValidMbti16(code: string): code is Mbti16Code {
  return (MBTI_TYPES_16 as readonly string[]).includes(code.toUpperCase());
}

/**
 * 类型预览页：按该类型倾向构造示意分布（非真实答题数据）。
 */
export function previewSpectraForType(mbti: string): AxisSpectrumRow[] | null {
  const u = mbti.toUpperCase();
  if (!isValidMbti16(u)) return null;
  const [c0, c1, c2, c3] = u.split("");
  const picks: { axis: QuestionItem["axis"]; ch: string }[] = [
    { axis: "EI", ch: c0 },
    { axis: "SN", ch: c1 },
    { axis: "TF", ch: c2 },
    { axis: "JP", ch: c3 },
  ];
  const strong = 7;
  const weak = 2;
  return picks.map(({ axis, ch }) => {
    const meta = AXIS_META[axis];
    const towardLeft = ch === meta.leftLetter;
    const left = towardLeft ? strong : weak;
    const right = towardLeft ? weak : strong;
    const total = left + right;
    const leftPercent = Math.round((left / total) * 1000) / 10;
    return {
      axis,
      title: meta.title,
      leftLetter: meta.leftLetter,
      rightLetter: meta.rightLetter,
      left,
      right,
      leftPercent,
      letter: ch,
    };
  });
}

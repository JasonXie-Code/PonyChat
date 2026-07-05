import type { QuestionBank, QuizVersion } from "./types";

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/**
 * 从 72 题题库中按四轴均衡抽取：
 * - 12 题：每轴随机 3 题
 * - 36 题：每轴随机 9 题
 * 返回的题号顺序已整体打乱，避免同一维度连续出现。
 */
export function buildQuizOrder(
  bank: QuestionBank,
  version: QuizVersion
): number[] {
  const byAxis = {
    EI: [] as number[],
    SN: [] as number[],
    TF: [] as number[],
    JP: [] as number[],
  };
  for (const it of bank.items) {
    byAxis[it.axis].push(it.id);
  }
  const perAxis = version === "q12" ? 3 : 9;
  const picked: number[] = [];
  for (const ax of ["EI", "SN", "TF", "JP"] as const) {
    const pool = shuffle(byAxis[ax]);
    if (pool.length < perAxis) {
      throw new Error(`axis ${ax} 题库不足 ${perAxis} 题`);
    }
    picked.push(...pool.slice(0, perAxis));
  }
  return shuffle(picked);
}

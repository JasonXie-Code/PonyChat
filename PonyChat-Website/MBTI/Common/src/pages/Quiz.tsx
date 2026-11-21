import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext";
import bankRaw from "@data/questions.json";
import type { QuestionBank, QuestionItem, Side } from "../lib/types";

const bank = bankRaw as QuestionBank;

function itemById(id: number): QuestionItem | undefined {
  return bank.items.find((i) => i.id === id);
}

function expectedCount(version: "q12" | "q36"): number {
  return version === "q12" ? 12 : 36;
}

export default function Quiz() {
  const { version, answers, setAnswer, quizOrder } = useSession();
  const navigate = useNavigate();
  const [idx, setIdx] = useState(0);

  const total = quizOrder.length;
  const currentId = quizOrder[idx];
  const current = currentId !== undefined ? itemById(currentId) : undefined;
  const answered = currentId !== undefined ? answers[currentId] : undefined;
  const completed = quizOrder.filter((id: number) => answers[id] !== undefined).length;
  const progress = total ? (completed / total) * 100 : 0;

  useEffect(() => {
    setIdx(0);
  }, [version, quizOrder.join(",")]);

  if (!version) {
    return (
      <div className="app-shell">
        <div className="card">
          <p>请先选择题量。</p>
          <Link to="/version">返回</Link>
        </div>
      </div>
    );
  }

  const okOrder =
    total === expectedCount(version) &&
    quizOrder.every((id: number) => itemById(id) !== undefined);

  if (!okOrder || total === 0) {
    return <Navigate to="/version" replace />;
  }

  function pick(side: Side) {
    if (currentId === undefined) return;
    setAnswer(currentId, side);
    if (idx + 1 >= total) {
      navigate("/result");
    } else {
      setIdx((i: number) => i + 1);
    }
  }

  const allDone =
    total > 0 && quizOrder.every((id: number) => answers[id] !== undefined);

  if (!current) {
    return (
      <div className="app-shell">
        <div className="card">
          <p>题目加载异常。</p>
          <Link to="/">返回首页</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <div className="nav-top">
        <Link to="/version">← 重选题量</Link>
        <span className="tag">
          {version === "q12" ? "12 题" : "36 题"}
        </span>
      </div>
      <div className="card" style={{ flex: 1 }}>
        <div className="progress">
          <div style={{ width: `${Math.min(100, progress)}%` }} />
        </div>
        <p className="muted" style={{ marginBottom: "0.35rem" }}>
          第 {idx + 1} / {total} 题
        </p>
        <h2 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.75rem" }}>
          {current.text}
        </h2>
        <div className="btn-row" style={{ marginTop: 0 }}>
          <button
            type="button"
            className={`option-btn ${answered === "L" ? "selected" : ""}`}
            onClick={() => pick("L")}
          >
            {current.optionLeft}
          </button>
          <button
            type="button"
            className={`option-btn ${answered === "R" ? "selected" : ""}`}
            onClick={() => pick("R")}
          >
            {current.optionRight}
          </button>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem", flexWrap: "wrap" }}>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={idx === 0}
            onClick={() => setIdx((i: number) => Math.max(0, i - 1))}
          >
            上一题
          </button>
          {allDone && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => navigate("/result")}
            >
              查看结果
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

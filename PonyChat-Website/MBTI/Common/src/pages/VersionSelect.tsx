import { Link, useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext";
import bankRaw from "@data/questions.json";
import { buildQuizOrder } from "../lib/quizSelection";
import type { QuestionBank, QuizVersion } from "../lib/types";

const bank = bankRaw as QuestionBank;

export default function VersionSelect() {
  const { setVersion, resetAnswers, setQuizOrder } = useSession();
  const navigate = useNavigate();

  function choose(v: QuizVersion) {
    resetAnswers();
    setVersion(v);
    setQuizOrder(buildQuizOrder(bank, v));
    navigate("/quiz");
  }

  return (
    <div className="app-shell">
      <div className="nav-top">
        <Link to="/demographics">← 上一步</Link>
      </div>
      <div className="card" style={{ flex: 1 }}>
        <h1>选择题量</h1>
        <p>
          题库共 <strong>72</strong> 题（四轴各 18 题）。每次测验会从题库中<strong>随机抽取</strong>：
          <strong>36 题</strong>版每轴 9 题，<strong>12 题</strong>版每轴 3 题；题目顺序<strong>打乱</strong>，避免连续同一维度。
        </p>
        <p className="muted">再次测验时会重新抽题，题目组合会有变化。</p>
        <div className="btn-row">
          <button type="button" className="btn btn-primary" onClick={() => choose("q36")}>
            36 题完整版
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => choose("q12")}>
            12 题简版
          </button>
        </div>
      </div>
    </div>
  );
}

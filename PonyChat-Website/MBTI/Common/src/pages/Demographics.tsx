import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext";

function validateAge(raw: string): string | null {
  const t = raw.trim();
  if (!t) return "请输入年龄";
  if (!/^\d+$/.test(t)) return "年龄须为整数";
  const n = parseInt(t, 10);
  if (n < 1 || n > 100) return "年龄须在 1–100 之间";
  return null;
}

export default function Demographics() {
  const { gender, age, setGender, setAge } = useSession();
  const initGender = gender === "男" || gender === "女" ? gender : "";
  const [localGender, setLocalGender] = useState(initGender);
  const [localAge, setLocalAge] = useState(age);
  const [ageTouched, setAgeTouched] = useState(false);

  const navigate = useNavigate();

  const ageMsg = ageTouched ? validateAge(localAge) : null;
  const ok =
    (localGender === "男" || localGender === "女") &&
    validateAge(localAge) === null;

  function handleNext() {
    setAgeTouched(true);
    if (validateAge(localAge)) return;
    if (localGender !== "男" && localGender !== "女") return;
    const n = parseInt(localAge.trim(), 10);
    setGender(localGender);
    setAge(String(n));
    navigate("/version");
  }

  return (
    <div className="app-shell">
      <div className="nav-top">
        <Link to="/">← 返回说明</Link>
      </div>
      <div className="card" style={{ flex: 1 }}>
        <h1>基本信息</h1>
        <p className="muted">用于统计与结果展示，仅存于本机。</p>
        <span className="muted" style={{ display: "block", marginBottom: "0.35rem" }}>
          性别
        </span>
        <div className="gender-row" role="group" aria-label="性别">
          <button
            type="button"
            className={`gender-btn ${localGender === "男" ? "selected" : ""}`}
            onClick={() => setLocalGender("男")}
            aria-pressed={localGender === "男"}
          >
            男
          </button>
          <button
            type="button"
            className={`gender-btn ${localGender === "女" ? "selected" : ""}`}
            onClick={() => setLocalGender("女")}
            aria-pressed={localGender === "女"}
          >
            女
          </button>
        </div>
        <label className="muted" htmlFor="a" style={{ display: "block", marginBottom: "0.35rem" }}>
          年龄
        </label>
        <input
          id="a"
          className={`mbti-input${ageTouched && ageMsg ? " mbti-input--invalid" : ""}`}
          inputMode="numeric"
          autoComplete="bday-year"
          value={localAge}
          onChange={(e) => setLocalAge(e.target.value)}
          onBlur={() => setAgeTouched(true)}
          placeholder="1–100 的整数"
          aria-invalid={ageTouched && ageMsg !== null}
        />
        {ageTouched && ageMsg ? (
          <p className="field-error" role="alert">
            {ageMsg}
          </p>
        ) : null}
        <div className="btn-row">
          <button type="button" className="btn btn-primary" disabled={!ok} onClick={handleNext}>
            下一步：选择题量
          </button>
        </div>
      </div>
    </div>
  );
}

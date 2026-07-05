import { Link } from "react-router-dom";
import { MBTI_TYPES_16 } from "../lib/scoring";

export default function TypeBrowse() {
  return (
    <div className="app-shell">
      <div className="nav-top">
        <Link to="/">首页</Link>
        <Link to="/wiki">百科</Link>
      </div>
      <div className="card" style={{ flex: 1 }}>
        <h1>16 型人格示例</h1>
        <p className="muted">
          选择类型可查看与测验结束页相同版式的示例结果（非本人数据）。
        </p>
        <div className="type-browse-grid" role="navigation" aria-label="十六型人格">
          {MBTI_TYPES_16.map((code) => (
            <Link key={code} to={`/types/${code}`} className="type-browse-btn">
              {code}
            </Link>
          ))}
        </div>
        <div className="btn-row" style={{ marginTop: "1.25rem" }}>
          <Link to="/demographics" className="btn btn-primary" style={{ textAlign: "center" }}>
            去做测验
          </Link>
        </div>
      </div>
    </div>
  );
}

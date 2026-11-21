import { Link } from "react-router-dom";
import { wikiEntries } from "@data/wiki";
import { useSiteConfig } from "../config/SiteConfigContext";

export default function Wiki() {
  const { wikiHeading, wikiSubtitle } = useSiteConfig();

  return (
    <div className="app-shell">
      <div className="nav-top">
        <Link to="/">首页</Link>
        <Link to="/result">上次结果</Link>
      </div>
      <div className="card" style={{ flex: 1 }}>
        <h1>{wikiHeading}</h1>
        <p className="muted">{wikiSubtitle}</p>
        <ul className="wiki-list">
          {wikiEntries.map((e) => (
            <li key={e.id}>
              <strong>{e.name}</strong>{" "}
              <span className="tag">{e.mbti}</span>
              <p style={{ margin: "0.35rem 0 0", fontSize: "0.9rem" }}>{e.blurb}</p>
            </li>
          ))}
        </ul>
        <div className="btn-row" style={{ marginTop: "1.25rem" }}>
          <Link to="/version" className="btn btn-secondary" style={{ textAlign: "center" }}>
            去做测试
          </Link>
        </div>
      </div>
    </div>
  );
}

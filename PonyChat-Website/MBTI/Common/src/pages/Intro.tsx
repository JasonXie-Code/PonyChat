import { Link } from "react-router-dom";
import { useSiteConfig } from "../config/SiteConfigContext";

export default function Intro() {
  const {
    introHeading,
    introP1Bold,
    introP1Rest,
    introP2,
    introP3,
  } = useSiteConfig();

  return (
    <div className="app-shell">
      <div className="card" style={{ flex: 1 }}>
        <h1>{introHeading}</h1>
        <p>
          <strong>{introP1Bold}</strong>
          {introP1Rest}
        </p>
        <p>{introP2}</p>
        <p className="muted">{introP3}</p>
        <div className="btn-row">
          <Link to="/demographics" className="btn btn-primary" style={{ textAlign: "center" }}>
            我已了解，继续
          </Link>
          <Link to="/types" className="btn btn-secondary" style={{ textAlign: "center" }}>
            浏览 16 种人格示例
          </Link>
        </div>
      </div>
    </div>
  );
}

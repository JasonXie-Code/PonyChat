import { Link, Outlet } from "react-router-dom";
import { useSiteConfig } from "../config/SiteConfigContext";

const MAIN_SITE = "https://www.ponychat.org/";

export default function SiteLayout() {
  const { headerNavMbtiLabel, footerNote } = useSiteConfig();

  return (
    <>
      <div className="bg-layer" aria-hidden="true" />
      <div className="mbti-frame">
        <header className="site-header mbti-header">
          <a className="brand" href={MAIN_SITE}>
            <img
              src="/logo/logoBK512.png"
              alt=""
              className="logo-img"
              width={44}
              height={44}
              decoding="async"
            />
            <span className="brand-text">PonyChat</span>
          </a>
          <nav className="header-nav" aria-label="页面导航">
            <a href={MAIN_SITE}>首页</a>
            <Link to="/">{headerNavMbtiLabel}</Link>
            <Link to="/types">16型浏览</Link>
            <Link to="/wiki">百科</Link>
          </nav>
        </header>

        <main className="mbti-main">
          <Outlet />
        </main>

        <footer className="site-footer mbti-footer">
          <p className="footer-note">
            {footerNote}
          </p>
          <p className="footer-links-inline">
            <a href={MAIN_SITE}>返回 PonyChat 主站</a>
          </p>
        </footer>
      </div>
    </>
  );
}

import { Link, Navigate, useParams } from "react-router-dom";
import { useSiteConfig } from "../config/SiteConfigContext";
import { useSession } from "../context/SessionContext";
import { getTypeProfile, shortTypeName } from "@data/mbtiTypes";
import { friendCompatForUser, partnerCompatForUser } from "@data/compatExplain";
import { ponyFor, ponyForPartner } from "@data/typicalPonies";
import AxisSpectrum from "../components/AxisSpectrum";
import TypeExplanation from "../components/TypeExplanation";
import {
  previewSpectraForType,
  recommendFriendPartner,
} from "../lib/scoring";

function displayCode(mbti: string): string {
  if (!mbti) return "";
  const code = mbti.toUpperCase();
  const zh = shortTypeName(mbti);
  return zh === code ? code : `${code} · ${zh}`;
}

export default function ResultPreview() {
  const { gender } = useSession();
  const { typicalLabel } = useSiteConfig();
  const { mbti: raw } = useParams<{ mbti: string }>();
  const mbti = (raw ?? "").toUpperCase();
  const spectra = previewSpectraForType(mbti);
  const profile = getTypeProfile(mbti);

  if (!spectra || !mbti || mbti.length !== 4) {
    return <Navigate to="/types" replace />;
  }

  const { friendType: friend, partnerType: partner } =
    recommendFriendPartner(mbti);

  const codeLine = displayCode(mbti);

  return (
    <div className="app-shell">
      <div className="nav-top">
        <Link to="/types">← 16 型列表</Link>
        <Link to="/">首页</Link>
        <Link to="/wiki">百科</Link>
      </div>
      <div className="card" style={{ flex: 1 }}>
        <h1>类型示例</h1>
        <p className="muted">
          <strong>{codeLine}</strong> 示例页，非本人测验数据。
        </p>
        <div style={{ margin: "0.5rem 0" }}>
          <p className="result-mbti-code">{codeLine}</p>
          <p style={{ margin: 0 }}>
            <span className="tag">{ponyFor(mbti)}</span>
          </p>
        </div>
        <p className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.75rem" }}>
          四轴分布为示意，请以实际测验为准。
        </p>
        <TypeExplanation code={mbti} profile={profile} />
        <AxisSpectrum rows={spectra} />
        <hr style={{ border: "none", borderTop: "1px solid #e1bee7", margin: "1rem 0" }} />
        <h2>做朋友可能更合拍</h2>
        <p>
          类型 <strong>{displayCode(friend)}</strong> · {typicalLabel}
          {ponyFor(friend)}
        </p>
        <p className="muted" style={{ fontSize: "0.8rem" }}>
          仅在外向/内向上相反，其余轴相同。
        </p>
        <p className="compat-why">{friendCompatForUser(mbti)}</p>
        <h2>伴侣向参考</h2>
        <p>
          类型 <strong>{displayCode(partner)}</strong> · {typicalLabel}
          {ponyForPartner(partner, gender)}
        </p>
        <p className="muted" style={{ fontSize: "0.8rem" }}>
          仅在判断/感知上相反，其余轴相同。
        </p>
        <p className="compat-why">{partnerCompatForUser(mbti)}</p>
        <div className="btn-row" style={{ marginTop: "1rem" }}>
          <Link to="/demographics" className="btn btn-primary" style={{ textAlign: "center" }}>
            亲自测一测
          </Link>
          <Link to="/types" className="btn btn-secondary" style={{ textAlign: "center" }}>
            返回 16 型列表
          </Link>
        </div>
      </div>
    </div>
  );
}

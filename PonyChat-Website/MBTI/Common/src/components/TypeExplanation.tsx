import { explainLetters, type TypeProfile } from "@data/mbtiTypes";
import { standardShortZh } from "../lib/mbtiStandardShortZh";
import { useSiteConfig } from "../config/SiteConfigContext";

export default function TypeExplanation({
  code,
  profile,
}: {
  code: string;
  profile: TypeProfile | null;
}) {
  const {
    typeExplanationEmptyHint,
    typeExplanationSubHeading,
  } = useSiteConfig();
  const rows = explainLetters(code);

  return (
    <section className="type-explanation">
      <h2>你的类型在说什么？</h2>
      {profile ? (
        <>
          <p className="type-explanation-nick">
            <span className="tag">{standardShortZh(code)}</span>
          </p>
          <div className="type-explanation-summary-wrap">
            {profile.summary.map((para, i) => (
              <p key={i} className="type-explanation-para">
                {para}
              </p>
            ))}
          </div>
        </>
      ) : (
        <p className="muted">{typeExplanationEmptyHint}</p>
      )}
      <h3 className="type-explanation-sub">{typeExplanationSubHeading}</h3>
      <p className="muted" style={{ fontSize: "0.8rem", marginBottom: "0.65rem" }}>
        以下为偏好倾向说明，非能力高低。
      </p>
      <ul className="type-explanation-letters">
        {rows.map((row, i) => (
          <li key={i}>
            <div className="type-explanation-letterline">
              <strong className="type-explanation-letter">{row.pole}</strong>
              <span className="type-explanation-dim"> · {row.dimLabel}</span>
            </div>
            <span className="type-explanation-text">{row.detail}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

import { useMemo } from "react";
import { Link, Navigate } from "react-router-dom";
import { useSiteConfig } from "../config/SiteConfigContext";
import { useSession } from "../context/SessionContext";
import bankRaw from "@data/questions.json";
import { getTypeProfile, shortTypeName } from "@data/mbtiTypes";
import { friendCompatForUser, partnerCompatForUser } from "@data/compatExplain";
import { ponyFor, ponyForPartner } from "@data/typicalPonies";
import AxisSpectrum from "../components/AxisSpectrum";
import TypeExplanation from "../components/TypeExplanation";
import {
  axisSpectra,
  recommendFriendPartner,
  scoreMbti,
  type AxisSpectrumRow,
} from "../lib/scoring";
import type { QuestionBank, QuizVersion, Side } from "../lib/types";

const bank = bankRaw as QuestionBank;

function expectedCount(version: QuizVersion): number {
  return version === "q12" ? 12 : 36;
}

function isComplete(
  version: QuizVersion,
  quizOrder: number[],
  answers: Record<number, Side>
): boolean {
  if (quizOrder.length !== expectedCount(version)) return false;
  return quizOrder.every((id) => answers[id] !== undefined);
}

function displayCode(mbti: string): string {
  if (!mbti) return "";
  const code = mbti.toUpperCase();
  const zh = shortTypeName(mbti);
  return zh === code ? code : `${code} · ${zh}`;
}

export default function Result() {
  const {
    typicalLabel,
    wikiLinkText,
  } = useSiteConfig();
  const { version, answers, gender, age, anonId, quizOrder } = useSession();

  const { mbti, friend, partner, spectra, profile } = useMemo(() => {
    if (
      !version ||
      !isComplete(version, quizOrder, answers)
    ) {
      return {
        mbti: "",
        friend: "",
        partner: "",
        spectra: [] as AxisSpectrumRow[],
        profile: null,
      };
    }
    const m = scoreMbti(bank, quizOrder, answers);
    const { friendType, partnerType } = recommendFriendPartner(m);
    const sp = axisSpectra(bank, quizOrder, answers);
    return {
      mbti: m,
      friend: friendType,
      partner: partnerType,
      spectra: sp,
      profile: getTypeProfile(m),
    };
  }, [version, quizOrder, answers]);

  if (!version) {
    return <Navigate to="/version" replace />;
  }

  if (!isComplete(version, quizOrder, answers)) {
    return (
      <div className="app-shell">
        <div className="card">
          <p>尚未答完所有题目。</p>
          <Link to="/quiz">返回答题</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <div className="card" style={{ flex: 1 }}>
        <h1>你的结果</h1>
        <p className="muted">
          {gender} · {age} 岁 · {version === "q12" ? "12 题简版" : "36 题完整版"}
        </p>
        <div style={{ margin: "0.5rem 0" }}>
          <p className="result-mbti-code">{displayCode(mbti)}</p>
          <p style={{ margin: 0 }}>
            <span className="tag">{ponyFor(mbti)}</span>
          </p>
        </div>
        <p className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.75rem" }}>
          以下为类型说明与各维倾向分布。
        </p>
        {mbti && <TypeExplanation code={mbti} profile={profile} />}
        {spectra.length > 0 && <AxisSpectrum rows={spectra} />}
        <hr className="card-divider" />
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
        <p className="muted result-meta" style={{ marginTop: "1rem", fontSize: "0.8rem" }}>
          本地匿名 ID：<code>{anonId}</code>
        </p>
        <div className="btn-row">
          <Link to="/wiki" className="btn btn-primary" style={{ textAlign: "center" }}>
            {wikiLinkText}
          </Link>
          <Link to="/version" className="btn btn-secondary" style={{ textAlign: "center" }}>
            再测一次
          </Link>
        </div>
      </div>
    </div>
  );
}

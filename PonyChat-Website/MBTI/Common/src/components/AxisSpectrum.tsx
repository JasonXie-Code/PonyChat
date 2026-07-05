import type { AxisSpectrumRow } from "../lib/scoring";

function tendencyHint(row: AxisSpectrumRow): string {
  const { leftPercent, leftLetter, rightLetter } = row;
  const d = Math.abs(leftPercent - 50);
  if (d <= 8) return "接近中间";
  if (leftPercent > 50) {
    return `更偏向 ${leftLetter}（左端约 ${leftPercent}%）`;
  }
  const rightPct = Math.round((100 - leftPercent) * 10) / 10;
  return `更偏向 ${rightLetter}（右端约 ${rightPct}%）`;
}

export default function AxisSpectrum({ rows }: { rows: AxisSpectrumRow[] }) {
  return (
    <div className="axis-spectrum">
      <h2 style={{ marginBottom: "0.65rem" }}>四轴分布</h2>
      <p className="muted" style={{ marginBottom: "1rem", fontSize: "0.82rem" }}>
        条带表示本次答题在每一维上的倾向：越靠两端越鲜明，靠中间表示两侧接近。
      </p>
      {rows.map((row) => (
        <div key={row.axis} className="axis-spectrum-row">
          <div className="axis-spectrum-head">
            <span className="axis-spectrum-title">{row.title}</span>
            <span className="axis-spectrum-verdict">
              判定：<strong>{row.letter}</strong>
            </span>
          </div>
          <div className="axis-spectrum-labels">
            <span>
              {row.leftLetter}
              <small>（{row.left}）</small>
            </span>
            <span>
              {row.rightLetter}
              <small>（{row.right}）</small>
            </span>
          </div>
          <div className="axis-spectrum-track" aria-hidden>
            <div
              className="axis-spectrum-fill"
              style={{
                width: `${row.leftPercent}%`,
                borderRadius:
                  row.leftPercent >= 99.5 ? "999px" : "999px 0 0 999px",
              }}
            />
            <div className="axis-spectrum-mid" />
          </div>
          <p className="axis-spectrum-hint">{tendencyHint(row)}</p>
        </div>
      ))}
    </div>
  );
}

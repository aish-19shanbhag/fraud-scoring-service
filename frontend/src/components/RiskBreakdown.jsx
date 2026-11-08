const LEVELS = [
  { key: "GREEN", label: "Approve", className: "seg-green" },
  { key: "AMBER", label: "Review", className: "seg-amber" },
  { key: "RED", label: "Block", className: "seg-red" },
];

export default function RiskBreakdown({ stats }) {
  const counts = stats?.by_risk_level || {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <section className="card grow">
      <h2>Risk breakdown</h2>
      <div className="bar">
        {total > 0 &&
          LEVELS.map((l) => {
            const share = (counts[l.key] || 0) / total;
            // Keep tiny segments visible: fraud is rare, so RED is usually < 2%.
            return share > 0 ? (
              <div
                key={l.key}
                className={`seg ${l.className}`}
                style={{ flexGrow: Math.max(share, 0.02) }}
                title={`${l.label}: ${counts[l.key]}`}
              />
            ) : null;
          })}
      </div>
      <div className="legend">
        {LEVELS.map((l) => (
          <div key={l.key} className="legend-item">
            <span className={`swatch ${l.className}`} />
            <span>
              {l.key} · {l.label}
            </span>
            <strong>{(counts[l.key] || 0).toLocaleString()}</strong>
            <span className="muted">
              {total ? `${(((counts[l.key] || 0) / total) * 100).toFixed(1)}%` : ""}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

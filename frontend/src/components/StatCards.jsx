const money = (n) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const pct = (n) => (n == null ? "—" : `${(n * 100).toFixed(1)}%`);

export default function StatCards({ stats }) {
  const cards = stats
    ? [
        { label: "Transactions scored", value: stats.total_transactions.toLocaleString() },
        { label: "Flag rate", value: pct(stats.flag_rate), hint: "AMBER + RED" },
        { label: "Awaiting review", value: stats.pending_reviews.toLocaleString(), tone: "amber" },
        { label: "Amount blocked", value: money(stats.amount_blocked), tone: "red" },
        { label: "Alert precision", value: pct(stats.review_precision), hint: "of reviewed alerts" },
        {
          label: "p95 scoring latency",
          value: stats.p95_latency_ms == null ? "—" : `${stats.p95_latency_ms.toFixed(1)} ms`,
        },
      ]
    : [];

  return (
    <section className="stats">
      {cards.map((c) => (
        <div key={c.label} className={`stat ${c.tone ? `stat-${c.tone}` : ""}`}>
          <span className="stat-label">{c.label}</span>
          <span className="stat-value">{c.value}</span>
          {c.hint && <span className="stat-hint">{c.hint}</span>}
        </div>
      ))}
      {!stats && <div className="muted">Loading metrics…</div>}
    </section>
  );
}

const time = (iso) =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

const REVIEW_LABELS = {
  CONFIRMED_FRAUD: "Confirmed fraud",
  FALSE_POSITIVE: "False positive",
  NOT_REQUIRED: "—",
};

export default function TransactionTable({ transactions, onReview }) {
  if (transactions.length === 0) {
    return <p className="muted empty">No transactions yet. Start the simulator to stream traffic.</p>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>User</th>
            <th>Merchant</th>
            <th className="right">Amount</th>
            <th>Country</th>
            <th>Risk</th>
            <th>Why</th>
            <th>Review</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((t) => (
            <tr key={t.transaction_id} className={`row-${t.risk_level}`}>
              <td className="mono">{time(t.event_time)}</td>
              <td className="mono">{t.user_id}</td>
              <td>
                {t.merchant}
                <div className="muted small">{t.merchant_category.replace("_", " ")}</div>
              </td>
              <td className="right mono">${t.amount.toFixed(2)}</td>
              <td>{t.country}</td>
              <td>
                <span className={`badge badge-${t.risk_level}`}>{t.risk_level}</span>
                <div className="score">
                  <div
                    className={`score-fill fill-${t.risk_level}`}
                    style={{ width: `${Math.max(t.risk_score * 100, 2)}%` }}
                  />
                </div>
                <span className="muted small mono">{t.risk_score.toFixed(3)}</span>
              </td>
              <td className="signals">
                {t.signals.slice(0, 3).map((s) => (
                  <div key={s}>{s}</div>
                ))}
              </td>
              <td>
                {t.review_status === "PENDING" ? (
                  <div className="actions">
                    <button className="btn btn-red" onClick={() => onReview(t.transaction_id, "CONFIRMED_FRAUD")}>
                      Fraud
                    </button>
                    <button className="btn" onClick={() => onReview(t.transaction_id, "FALSE_POSITIVE")}>
                      Legit
                    </button>
                  </div>
                ) : (
                  <span className="muted small">{REVIEW_LABELS[t.review_status]}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

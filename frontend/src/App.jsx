import { useCallback, useEffect, useMemo, useState } from "react";
import { api, connectFeed } from "./api";
import StatCards from "./components/StatCards";
import RiskBreakdown from "./components/RiskBreakdown";
import TransactionTable from "./components/TransactionTable";
import ModelPanel from "./components/ModelPanel";

const MAX_ROWS = 200;
const FILTERS = ["ALL", "RED", "AMBER", "GREEN", "PENDING"];

export default function App() {
  const [transactions, setTransactions] = useState([]);
  const [stats, setStats] = useState(null);
  const [model, setModel] = useState(null);
  const [feedStatus, setFeedStatus] = useState("connecting");
  // Optional ?filter=red|amber|green|pending in the URL sets the starting view.
  const [filter, setFilter] = useState(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("filter")?.toUpperCase();
    return FILTERS.includes(fromUrl) ? fromUrl : "ALL";
  });
  const [error, setError] = useState(null);

  // Insert a new transaction, or replace it if we already have it (after a review).
  const upsert = useCallback((txn) => {
    setTransactions((current) => {
      const rest = current.filter((t) => t.transaction_id !== txn.transaction_id);
      const exists = rest.length !== current.length;
      return exists
        ? current.map((t) => (t.transaction_id === txn.transaction_id ? txn : t))
        : [txn, ...rest].slice(0, MAX_ROWS);
    });
  }, []);

  useEffect(() => {
    api
      .listTransactions(100)
      .then((page) => setTransactions(page.items))
      .catch((e) => setError(e.message));
    api.model().then(setModel).catch(() => {});
    return connectFeed((message) => upsert(message.data), setFeedStatus);
  }, [upsert]);

  useEffect(() => {
    const load = () =>
      api
        .stats()
        .then((s) => {
          setStats(s);
          setError(null);
        })
        .catch((e) => setError(e.message));
    load();
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, []);

  const review = async (transactionId, status) => {
    try {
      upsert(await api.review(transactionId, status));
    } catch (e) {
      setError(e.message);
    }
  };

  const visible = useMemo(() => {
    if (filter === "ALL") return transactions;
    if (filter === "PENDING") return transactions.filter((t) => t.review_status === "PENDING");
    return transactions.filter((t) => t.risk_level === filter);
  }, [transactions, filter]);

  return (
    <div className="page">
      <header className="header">
        <div>
          <h1>Fraud Monitor</h1>
          <p className="subtitle">Real-time transaction risk scoring</p>
        </div>
        <span className={`feed feed-${feedStatus}`}>
          <span className="dot" /> {feedStatus === "live" ? "Live" : feedStatus}
        </span>
      </header>

      {error && <div className="error">Cannot reach the API: {error}</div>}

      <StatCards stats={stats} />

      <div className="row">
        <RiskBreakdown stats={stats} />
        <ModelPanel model={model} />
      </div>

      <section className="card">
        <div className="table-header">
          <h2>Transactions</h2>
          <div className="filters">
            {FILTERS.map((f) => (
              <button
                key={f}
                className={`chip ${filter === f ? "chip-active" : ""}`}
                onClick={() => setFilter(f)}
              >
                {f === "PENDING" ? "Needs review" : f.charAt(0) + f.slice(1).toLowerCase()}
              </button>
            ))}
          </div>
        </div>
        <TransactionTable transactions={visible} onReview={review} />
      </section>
    </div>
  );
}

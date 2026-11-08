export default function ModelPanel({ model }) {
  if (!model) return <section className="card model">Loading model…</section>;
  const t = model.metrics.test;
  return (
    <section className="card model">
      <h2>Model</h2>
      <dl>
        <dt>Version</dt>
        <dd className="mono">{model.version}</dd>
        <dt>PR-AUC (test)</dt>
        <dd>{t.pr_auc.toFixed(3)}</dd>
        <dt>Block precision / recall</dt>
        <dd>
          {(t.red_block.precision * 100).toFixed(0)}% / {(t.red_block.recall * 100).toFixed(0)}%
        </dd>
        <dt>Thresholds</dt>
        <dd>
          <span className="badge badge-AMBER">≥ {model.amber_threshold.toFixed(3)}</span>{" "}
          <span className="badge badge-RED">≥ {model.red_threshold.toFixed(3)}</span>
        </dd>
      </dl>
    </section>
  );
}

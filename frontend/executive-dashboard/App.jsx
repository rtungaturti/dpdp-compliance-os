import { useState, useEffect } from "react";

const API = {
  score: "http://localhost:8506",
  hitl:  "http://localhost:8303",
  bias:  "http://localhost:8103",
  pep:   "http://localhost:8104",
  shadow:"http://localhost:8701",
};

function ScoreMeter({ score, tier }) {
  const pct = (score / 1000) * 100;
  const tierColors = {
    platinum: "#1D9E75", gold: "#BA7517", silver: "#888780",
    bronze: "#D85A30",  at_risk: "#E24B4A", critical: "#A32D2D",
  };
  const color = tierColors[tier] || "#888780";
  return (
    <div style={{ textAlign: "center", padding: "24px 0" }}>
      <svg viewBox="0 0 200 110" width="200" style={{ overflow: "visible" }}>
        <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="#D3D1C7" strokeWidth="16" strokeLinecap="round"/>
        <path
          d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke={color} strokeWidth="16" strokeLinecap="round"
          strokeDasharray={`${pct * 2.51} 251`}
          style={{ transition: "stroke-dasharray 1s ease" }}
        />
        <text x="100" y="88" textAnchor="middle" fontSize="28" fontWeight="600" fill="currentColor">{score}</text>
        <text x="100" y="105" textAnchor="middle" fontSize="11" fill="#888780">{tier?.toUpperCase()}</text>
      </svg>
      <div style={{ fontSize: 12, color: "#888780", marginTop: 4 }}>out of 1,000</div>
    </div>
  );
}

function MetricCard({ label, value, sub, accent }) {
  return (
    <div style={{
      background: "var(--color-background-secondary, #f5f5f0)",
      borderRadius: 8, padding: "14px 16px", minWidth: 0,
    }}>
      <div style={{ fontSize: 11, color: "#888780", marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 500, color: accent || "currentColor" }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "#888780", marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

function DimensionBar({ label, score, max }) {
  const pct = Math.round((score / max) * 100);
  const color = pct >= 80 ? "#1D9E75" : pct >= 60 ? "#BA7517" : "#E24B4A";
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
        <span style={{ color: "#3d3d3a" }}>{label}</span>
        <span style={{ color, fontWeight: 500 }}>{pct}%</span>
      </div>
      <div style={{ height: 5, background: "#D3D1C7", borderRadius: 99 }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 99, transition: "width 0.8s ease" }}/>
      </div>
    </div>
  );
}

function HITLQueue({ tasks }) {
  const priorityColor = { critical: "#E24B4A", high: "#D85A30", medium: "#BA7517", low: "#888780" };
  if (!tasks?.length) return <div style={{ fontSize: 12, color: "#888780", padding: "16px 0" }}>No pending tasks</div>;
  return (
    <div>
      {tasks.slice(0, 6).map(t => (
        <div key={t.task_id} style={{
          display: "flex", alignItems: "center", gap: 10, padding: "8px 0",
          borderBottom: "0.5px solid #D3D1C7",
        }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: priorityColor[t.priority] || "#888780", flexShrink: 0 }}/>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.title}</div>
            <div style={{ fontSize: 10, color: "#888780" }}>{t.task_type?.replace(/_/g, " ")} · due {new Date(t.due_at).toLocaleDateString()}</div>
          </div>
          <span style={{
            fontSize: 10, padding: "2px 7px", borderRadius: 99,
            background: priorityColor[t.priority] + "22", color: priorityColor[t.priority],
          }}>{t.priority}</span>
        </div>
      ))}
    </div>
  );
}

const MOCK_SCORE = {
  total_score: 724, tier: "silver",
  tier_description: "Adequate compliance — improvement areas identified",
  dimension_scores: [
    { dimension: "consent_management",      raw_score: 160, max_score: 200 },
    { dimension: "data_rights_fulfillment", raw_score: 155, max_score: 200 },
    { dimension: "breach_response",         raw_score: 120, max_score: 150 },
    { dimension: "ai_governance",           raw_score: 90,  max_score: 150 },
    { dimension: "data_minimisation",       raw_score: 75,  max_score: 100 },
    { dimension: "cross_border_compliance", raw_score: 70,  max_score: 100 },
    { dimension: "documentation_audit",     raw_score: 54,  max_score: 100 },
  ],
  top_risks: [
    "DPO not appointed — mandatory for SDF (DPDP §10(1))",
    "Documentation <80% complete",
    "1 cross-border violation in last 12 months",
  ],
  quick_wins: [
    "Publish algorithmic accountability report",
    "Issue signed consent receipts to all principals",
    "Complete ROPA and DPIAs",
  ],
};

const MOCK_HITL = {
  tasks: [
    { task_id: "1", title: "Erasure request — 12,000 records", task_type: "erasure_large_scale", priority: "high", due_at: new Date(Date.now() + 86400000 * 2).toISOString() },
    { task_id: "2", title: "DPIA approval: ML credit scoring v3", task_type: "dpia_approval", priority: "medium", due_at: new Date(Date.now() + 86400000 * 5).toISOString() },
    { task_id: "3", title: "Cross-border transfer — US partner", task_type: "cross_border_approval", priority: "critical", due_at: new Date(Date.now() + 14400000).toISOString() },
    { task_id: "4", title: "AI bias alert: loan decisioning model", task_type: "ai_model_deployment", priority: "high", due_at: new Date(Date.now() + 86400000).toISOString() },
  ],
  by_priority: { critical: 1, high: 2, medium: 1, low: 0 },
};

export default function ExecutiveDashboard() {
  const [score, setScore]   = useState(MOCK_SCORE);
  const [hitl, setHitl]     = useState(MOCK_HITL);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(new Date());

  const refresh = async () => {
    setLoading(true);
    try {
      const [scoreRes, hitlRes] = await Promise.allSettled([
        fetch(`${API.score}/score/compute`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entity_id: "demo-org", entity_name: "Demo Organisation",
            consent: { total_consents: 50000, valid_consents: 47000, withdrawal_response_avg_hours: 18, child_consent_compliant: true, consent_receipts_issued: false },
            rights: { total_requests: 120, completed_on_time: 108, average_response_days: 22, automated_fulfillment_rate: 0.4 },
            breach: { breaches_last_12m: 1, avg_detection_hours: 8, avg_notification_hours: 65, remediation_complete: true },
            ai_governance: { ai_systems_inventoried: true, dpias_completed: 3, bias_evaluations_run: 2, algorithmic_report_published: false, dpo_appointed: false },
            cross_border_violations_last_12m: 1,
            data_minimisation_score: 0.75,
            documentation_completeness: 0.54,
          }),
        }).then(r => r.json()),
        fetch(`${API.hitl}/hitl/queue?limit=10`).then(r => r.json()),
      ]);
      if (scoreRes.status === "fulfilled") setScore(scoreRes.value);
      if (hitlRes.status === "fulfilled") setHitl(hitlRes.value);
      setLastUpdated(new Date());
    } catch (e) {
      // Use mock data if services not running
    }
    setLoading(false);
  };

  useEffect(() => { refresh(); }, []);

  const dims = score?.dimension_scores || [];

  return (
    <div style={{ padding: "20px 16px", maxWidth: 900, margin: "0 auto", fontFamily: "var(--font-sans, system-ui)" }}>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20, flexWrap: "wrap", gap: 8 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 500 }}>DPDP Compliance OS</h1>
          <div style={{ fontSize: 12, color: "#888780", marginTop: 2 }}>Executive Dashboard · Updated {lastUpdated.toLocaleTimeString()}</div>
        </div>
        <button
          onClick={refresh}
          style={{ background: "transparent", border: "0.5px solid #D3D1C7", borderRadius: 8, padding: "6px 14px", fontSize: 12, cursor: "pointer", opacity: loading ? 0.5 : 1 }}
        >
          {loading ? "Refreshing…" : "↻ Refresh"}
        </button>
      </div>

      {/* Score + summary row */}
      <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 16, marginBottom: 16 }}>
        <div style={{ background: "var(--color-background-secondary, #f5f5f0)", borderRadius: 12, border: "0.5px solid #D3D1C7" }}>
          <ScoreMeter score={score?.total_score || 0} tier={score?.tier} />
          <div style={{ padding: "0 16px 16px", fontSize: 11, color: "#888780", textAlign: "center", lineHeight: 1.5 }}>
            {score?.tier_description}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
            <MetricCard label="HITL Queue" value={hitl?.tasks?.length || 0} sub="pending reviews" accent={hitl?.by_priority?.critical > 0 ? "#E24B4A" : undefined} />
            <MetricCard label="Critical Alerts" value={hitl?.by_priority?.critical || 0} sub="≤4h SLA" accent="#E24B4A" />
            <MetricCard label="Penalty Eligible" value={score?.penalty_reduction_eligible ? "Yes" : "No"} sub="score-based reduction" accent={score?.penalty_reduction_eligible ? "#1D9E75" : "#888780"} />
          </div>
          <div style={{ background: "var(--color-background-secondary, #f5f5f0)", borderRadius: 12, border: "0.5px solid #D3D1C7", padding: "14px 16px" }}>
            <div style={{ fontSize: 11, color: "#888780", marginBottom: 10, fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.05em" }}>Top risks</div>
            {(score?.top_risks || []).map((r, i) => (
              <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6, fontSize: 12 }}>
                <span style={{ color: "#E24B4A", flexShrink: 0 }}>•</span>
                <span style={{ color: "#3d3d3a" }}>{r}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Dimensions + HITL side by side */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
        <div style={{ background: "var(--color-background-secondary, #f5f5f0)", borderRadius: 12, border: "0.5px solid #D3D1C7", padding: "16px" }}>
          <div style={{ fontSize: 11, fontWeight: 500, color: "#888780", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 14 }}>Compliance dimensions</div>
          {dims.map(d => (
            <DimensionBar
              key={d.dimension}
              label={d.dimension.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
              score={d.raw_score}
              max={d.max_score}
            />
          ))}
        </div>

        <div style={{ background: "var(--color-background-secondary, #f5f5f0)", borderRadius: 12, border: "0.5px solid #D3D1C7", padding: "16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 500, color: "#888780", textTransform: "uppercase", letterSpacing: "0.05em" }}>HITL review queue</div>
            <div style={{ display: "flex", gap: 6 }}>
              {Object.entries(hitl?.by_priority || {}).filter(([,v]) => v > 0).map(([p, v]) => (
                <span key={p} style={{
                  fontSize: 10, padding: "2px 6px", borderRadius: 99,
                  background: { critical:"#FCEBEB", high:"#FAECE7", medium:"#FAEEDA", low:"#F1EFE8" }[p],
                  color: { critical:"#A32D2D", high:"#993C1D", medium:"#854F0B", low:"#5F5E5A" }[p],
                }}>{v} {p}</span>
              ))}
            </div>
          </div>
          <HITLQueue tasks={hitl?.tasks} />
        </div>
      </div>

      {/* Quick wins */}
      <div style={{ background: "#E1F5EE", borderRadius: 12, border: "0.5px solid #9FE1CB", padding: "14px 16px" }}>
        <div style={{ fontSize: 11, fontWeight: 500, color: "#085041", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>Quick wins to improve score</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 8 }}>
          {(score?.quick_wins || []).map((w, i) => (
            <div key={i} style={{ display: "flex", gap: 8, fontSize: 12 }}>
              <span style={{ color: "#1D9E75", flexShrink: 0 }}>✓</span>
              <span style={{ color: "#085041" }}>{w}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 14, fontSize: 10, color: "#888780", textAlign: "right" }}>
        Service APIs: Compliance Score :8506 · HITL :8303 · Bias Monitor :8103
      </div>
    </div>
  );
}

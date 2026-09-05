import React, { useState, useEffect, useRef } from 'react';
import {
  ShieldCheck,
  Lock,
  Key,
  Layers,
  FileCheck,
  Split,
  Copy,
  Check,
  Cpu,
  ShoppingBag,
  RefreshCw,
  Database,
  Terminal,
  Clock,
  Zap,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Play,
  Pause,
  ExternalLink,
} from 'lucide-react';
import { runMultiLegJourney } from '../services/api';

/* ──────────── Helpers ──────────── */
function formatPaise(v) {
  if (v == null || v === undefined) return '—';
  return `₹${(v / 100).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(part, whole) {
  if (!whole) return '0';
  return ((part / whole) * 100).toFixed(1);
}

export default function TransactionReactor({ onSwitchToAuditLedger, onLedgerChange }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [journeyData, setJourneyData] = useState(null);
  const [goal, setGoal] = useState('I need a birthday cake and candles under ₹1500');
  const [spendCap, setSpendCap] = useState(1500);
  const [scenario, setScenario] = useState('partial_failure');
  const [expandedDrawers, setExpandedDrawers] = useState({});
  const [copiedKey, setCopiedKey] = useState(null);
  const [isAutoScrolling, setIsAutoScrolling] = useState(false);
  const autoScrollTimerRef = useRef(null);

  /* NO mount-time auto-execution — page opens idle */

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await runMultiLegJourney(goal, spendCap * 100, scenario);
      setJourneyData(data);
      if (onLedgerChange) onLedgerChange();
    } catch (err) {
      console.error('Journey execution failed:', err);
      setError(err.message || 'Failed to connect to backend engine.');
    } finally {
      setLoading(false);
    }
  };

  const toggleDrawer = (key) => {
    setExpandedDrawers((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleCopy = (text, key) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1800);
  };

  const scrollToChapter = (id) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const handleToggleAutoScroll = () => {
    if (!journeyData) return;
    if (isAutoScrolling) {
      setIsAutoScrolling(false);
      if (autoScrollTimerRef.current) clearInterval(autoScrollTimerRef.current);
    } else {
      setIsAutoScrolling(true);
      let step = 1;
      scrollToChapter('chapter-01');
      autoScrollTimerRef.current = setInterval(() => {
        step += 1;
        if (step > 9) {
          setIsAutoScrolling(false);
          clearInterval(autoScrollTimerRef.current);
        } else {
          scrollToChapter(`chapter-0${step}`);
        }
      }, 3200);
    }
  };

  useEffect(() => {
    return () => {
      if (autoScrollTimerRef.current) clearInterval(autoScrollTimerRef.current);
    };
  }, []);

  /* ═════════════ IDLE STATE ═════════════ */
  if (!journeyData && !loading && !error) {
    return (
      <div className="stream-container">
        <div className="chapter-node" style={{ padding: '40px 20px' }}>
          <div style={{ textAlign: 'center', marginBottom: '32px' }}>
            <div style={{ fontFamily: 'var(--font-macro)', fontSize: '1.5rem', fontWeight: 900, letterSpacing: '0.15em', color: 'var(--text-phosphor)', marginBottom: '8px' }}>
              GUIDED TRANSACTION JOURNEY
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)', maxWidth: '600px', margin: '0 auto', lineHeight: 1.6 }}>
              No live journey executed yet. Configure parameters and click RUN to execute a genuine multi-merchant transaction through the real M3–M8 engine.
            </div>
          </div>

          <div style={{ maxWidth: '520px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* Goal */}
            <div>
              <label style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)', letterSpacing: '0.1em', display: 'block', marginBottom: '5px' }}>NATURAL LANGUAGE GOAL</label>
              <input
                type="text" value={goal} onChange={(e) => setGoal(e.target.value)}
                style={{ width: '100%', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', padding: '10px 12px', background: 'var(--bg-recessed)', border: '1px solid var(--border-line)', color: 'var(--text-phosphor)', outline: 'none' }}
              />
            </div>

            {/* Spend cap */}
            <div>
              <label style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)', letterSpacing: '0.1em', display: 'block', marginBottom: '5px' }}>SPEND CAP (₹)</label>
              <input
                type="number" value={spendCap} onChange={(e) => setSpendCap(Number(e.target.value))}
                style={{ width: '160px', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', padding: '10px 12px', background: 'var(--bg-recessed)', border: '1px solid var(--border-line)', color: 'var(--text-phosphor)', outline: 'none' }}
              />
            </div>

            {/* Scenario */}
            <div>
              <label style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)', letterSpacing: '0.1em', display: 'block', marginBottom: '5px' }}>SCENARIO</label>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={() => setScenario('all_success')} className={`btn ${scenario === 'all_success' ? 'btn-primary' : 'btn-secondary'}`}
                  style={{ fontSize: '0.68rem', padding: '8px 14px', flex: 1 }}>
                  <CheckCircle2 size={12} /><span>ALL SUCCESS</span>
                </button>
                <button onClick={() => setScenario('partial_failure')} className={`btn ${scenario === 'partial_failure' ? 'btn-danger' : 'btn-secondary'}`}
                  style={{ fontSize: '0.68rem', padding: '8px 14px', flex: 1 }}>
                  <AlertTriangle size={12} /><span>LEG 2 STOCK EXHAUSTION</span>
                </button>
              </div>
            </div>

            {/* Run button */}
            <button onClick={loadData} className="btn btn-primary" style={{ marginTop: '12px', padding: '14px', fontSize: '0.82rem', fontWeight: 900, letterSpacing: '0.1em' }}>
              <Zap size={16} /><span>RUN LIVE JOURNEY</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  /* ═════════════ LOADING STATE ═════════════ */
  if (loading) {
    return (
      <div className="stream-container">
        <div className="chapter-node" style={{ textAlign: 'center', padding: '80px 20px' }}>
          <RefreshCw size={28} style={{ color: 'var(--accent-terminal)', animation: 'spin 1s linear infinite', marginBottom: '16px' }} />
          <div style={{ fontFamily: 'var(--font-macro)', fontSize: '1rem', fontWeight: 800, color: 'var(--text-phosphor)', letterSpacing: '0.12em', marginBottom: '8px' }}>
            EXECUTING LIVE JOURNEY
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            Running real AI deliberation → basket planning → JIT revalidation → webhook capture…
          </div>
        </div>
      </div>
    );
  }

  /* ═════════════ ERROR STATE ═════════════ */
  if (error && !journeyData) {
    return (
      <div className="stream-container">
        <div className="chapter-node" style={{ padding: '40px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
            <XCircle size={20} style={{ color: 'var(--accent-red)' }} />
            <span style={{ fontFamily: 'var(--font-macro)', fontSize: '0.9rem', fontWeight: 800, color: 'var(--accent-red)', letterSpacing: '0.1em' }}>ENGINE ERROR</span>
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-label)', background: 'var(--bg-recessed)', padding: '14px', border: '1px solid var(--border-line)', marginBottom: '16px', whiteSpace: 'pre-wrap' }}>{error}</div>
          <button onClick={loadData} className="btn btn-secondary" style={{ fontSize: '0.72rem' }}>
            <RefreshCw size={12} /><span>RETRY</span>
          </button>
        </div>
      </div>
    );
  }

  /* ═════════════ ACTIVE STATE — journey completed ═════════════ */
  const d = journeyData;
  if (!d) return null;

  const legs = d.legs || [];
  const planLegs = d.plan?.legs || [];
  const events = d.audit?.events || [];
  const preExec = d.reservation?.pre_execution || {};
  const postExec = d.reservation?.post_execution || {};

  const reservedPct = pct(preExec.reserved_paise, preExec.spend_cap_paise);
  const capturedPct = pct(d.settlement?.captured_paise, d.settlement?.authorized_paise);

  return (
    <div className="stream-container">

      {/* ── STICKY HUD ── */}
      <div className="sticky-narrative-hud">
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{ background: 'var(--accent-terminal)', color: '#052414', padding: '3px 7px', fontFamily: 'var(--font-mono)', fontWeight: 900, fontSize: '0.65rem', letterSpacing: '0.05em' }}>
            RUN {d.run_id}
          </div>
          <span style={{ fontFamily: 'var(--font-macro)', fontWeight: 700, fontSize: '0.82rem', color: 'var(--text-phosphor)' }}>
            CAP {formatPaise(d.intent?.spend_cap_paise)}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontFamily: 'var(--font-mono)', fontSize: '0.66rem', background: 'var(--bg-recessed)', border: '1px solid var(--border-line)', padding: '4px 10px' }}>
          <span style={{ color: 'var(--text-muted)' }}>CAPTURED:</span>
          <span style={{ color: 'var(--accent-terminal)', fontWeight: 700 }}>{formatPaise(d.settlement?.captured_paise)}</span>
          <span style={{ color: 'var(--border-line)' }}>|</span>
          <span style={{ color: 'var(--text-muted)' }}>RELEASED:</span>
          <span style={{ color: 'var(--accent-steel)', fontWeight: 700 }}>{formatPaise(d.settlement?.released_paise)}</span>
          <span style={{ color: 'var(--border-line)' }}>|</span>
          <span style={{ color: d.settlement?.plan_status === 'COMPLETE' ? 'var(--accent-terminal)' : 'var(--accent-amber)', fontWeight: 700 }}>
            {d.settlement?.plan_status}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          {journeyData && (
            <button className={`btn ${isAutoScrolling ? 'btn-danger' : 'btn-primary'}`} onClick={handleToggleAutoScroll} style={{ fontSize: '0.66rem', padding: '4px 9px' }}>
              {isAutoScrolling ? <><Pause size={10} /><span>PAUSE</span></> : <><Play size={10} /><span>REPLAY TRACE</span></>}
            </button>
          )}
          <select value={scenario} onChange={(e) => setScenario(e.target.value)} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.63rem', padding: '4px 6px', background: 'var(--bg-recessed)', color: 'var(--text-label)', border: '1px solid var(--border-line)', cursor: 'pointer' }}>
            <option value="partial_failure">PARTIAL FAILURE</option>
            <option value="all_success">ALL SUCCESS</option>
          </select>
          <button onClick={loadData} disabled={loading} className="btn btn-secondary" style={{ fontSize: '0.63rem', padding: '4px 8px' }}>
            <RefreshCw size={10} /><span>RUN AGAIN</span>
          </button>
        </div>
      </div>

      {/* ═══════ CH01 — USER GOAL ═══════ */}
      <div className="chapter-node" id="chapter-01">
        <ChapterHeader num="01" tag="INITIATE" title="User Goal & Spend Boundary" badge={formatPaise(d.intent?.spend_cap_paise)} badgeColor="badge-cyan" />
        <GuaranteeCallout icon={<ShieldCheck size={14} />} text={`Spend cap: ${formatPaise(d.intent?.spend_cap_paise)} · Scenario: ${d.scenario}`} color="var(--accent-cyan)" />

        <div className="metric-grid">
          <DataMetricCard label="RAW QUERY" value={`"${d.goal}"`} mono />
          <DataMetricCard label="SPEND CAP" value={formatPaise(d.intent?.spend_cap_paise)} />
          <DataMetricCard label="NONCE" value={d.intent?.nonce?.slice(0, 16) + '…'} mono />
          <DataMetricCard label="INTENT ID" value={d.intent?.intent_id?.slice(0, 12) + '…'} mono />
        </div>

        <EvidenceDrawer label="RAW INTENT CREDENTIAL" drawerKey="ch01_raw" isExpanded={expandedDrawers['ch01_raw']} onToggle={toggleDrawer} data={d.intent} copyKey="raw_intent" copiedKey={copiedKey} onCopy={handleCopy} />
      </div>
      <ConduitConnector />

      {/* ═══════ CH02 — AI DELIBERATION ═══════ */}
      <div className="chapter-node" id="chapter-02">
        <ChapterHeader num="02" tag="DELIBERATE" title="AI Buyer Agent Deliberation" badge={d.ai?.executed ? 'GEMINI LIVE' : 'DETERMINISTIC FALLBACK'} badgeColor={d.ai?.executed ? 'badge-green' : 'badge-amber'} />
        <GuaranteeCallout icon={<Cpu size={14} />} text={d.ai?.llm_boundary_guarantee} color="var(--accent-amber)" />

        <div className="metric-grid">
          <DataMetricCard label="AI EXECUTED" value={d.ai?.executed ? 'YES — Live LLM' : 'NO — Heuristic Fallback'} />
          <DataMetricCard label="CATALOG CANDIDATES" value={d.ai?.catalog_candidates_count} />
          <DataMetricCard label="PROPOSED ITEMS" value={d.ai?.proposed_items?.length || 0} />
        </div>

        {d.ai?.llm_reasoning && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-label)', background: 'var(--bg-recessed)', padding: '10px 12px', border: '1px solid var(--border-line)', marginTop: '10px', fontStyle: 'italic' }}>
            LLM: "{d.ai.llm_reasoning}"
          </div>
        )}

        {d.ai?.candidate_merchants?.length > 0 && (
          <div style={{ marginTop: '12px' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: '6px' }}>CANDIDATE MERCHANT QUOTES</div>
            <table className="audit-table">
              <thead><tr><th>MERCHANT</th><th>STATUS</th><th>QUOTE</th></tr></thead>
              <tbody>
                {d.ai.candidate_merchants.map((cm, i) => (
                  <tr key={i}>
                    <td>{cm.name || cm.merchant_id}</td>
                    <td><span className={`badge ${cm.status === 'ELIGIBLE' ? 'badge-green' : 'badge-amber'}`}>{cm.status}</span></td>
                    <td>{cm.total_paise ? formatPaise(cm.total_paise) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <EvidenceDrawer label="RAW AI DELIBERATION" drawerKey="ch02_raw" isExpanded={expandedDrawers['ch02_raw']} onToggle={toggleDrawer} data={d.ai} copyKey="raw_ai" copiedKey={copiedKey} onCopy={handleCopy} />
      </div>
      <ConduitConnector />

      {/* ═══════ CH03 — INTENT BOUNDARY ═══════ */}
      <div className="chapter-node" id="chapter-03">
        <ChapterHeader num="03" tag="VERIFY" title="Cryptographic Intent Boundary" badge="ES256 VERIFIED" badgeColor="badge-green" />
        <GuaranteeCallout icon={<Key size={14} />} text={`NIST P-256 signed credential. Spend cap: ${formatPaise(d.intent?.spend_cap_paise)}`} color="var(--accent-green)" />

        <div className="metric-grid">
          <DataMetricCard label="VERIFIED" value={d.intent?.verified ? 'TRUE' : 'FALSE'} />
          <DataMetricCard label="CATEGORIES" value={d.intent?.allowed_categories?.join(', ')} />
          <DataMetricCard label="MERCHANTS" value={d.intent?.allowed_merchant_ids?.join(', ')} mono />
          <DataMetricCard label="VALID WINDOW" value={`${d.intent?.not_before?.slice(11, 19) || '?'} → ${d.intent?.expires_at?.slice(11, 19) || '?'} UTC`} />
        </div>
      </div>
      <ConduitConnector />

      {/* ═══════ CH04 — PURCHASE PLAN ═══════ */}
      <div className="chapter-node" id="chapter-04">
        <ChapterHeader num="04" tag="PLAN" title="Multi-Merchant Purchase Plan" badge={`${d.plan?.legs_count || 0} LEGS`} badgeColor="badge-cyan" />
        <GuaranteeCallout icon={<Layers size={14} />} text={`1 Intent → 1 Plan → ${d.plan?.legs_count || 0} Independent Mandates. Total authorized: ${formatPaise(d.plan?.total_authorized_paise)}`} color="var(--accent-cyan)" />

        <div className="metric-grid">
          <DataMetricCard label="PLAN ID" value={d.plan?.plan_id?.slice(0, 12) + '…'} mono />
          <DataMetricCard label="TOTAL AUTHORIZED" value={formatPaise(d.plan?.total_authorized_paise)} />
          <DataMetricCard label="LEGS" value={d.plan?.legs_count} />
        </div>

        {planLegs.map((leg, i) => (
          <div key={leg.leg_id || i} style={{ marginTop: '12px', padding: '12px', background: 'var(--bg-recessed)', border: '1px solid var(--border-line)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <span style={{ fontFamily: 'var(--font-macro)', fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-phosphor)' }}>
                LEG {String.fromCharCode(65 + i)} — {leg.merchant_name || leg.merchant_id}
              </span>
              <span className={`badge ${leg.status === 'PAYMENT_CAPTURED' ? 'badge-green' : leg.status === 'RELEASED' ? 'badge-amber' : 'badge-cyan'}`}>{leg.status}</span>
            </div>
            <div className="metric-grid">
              <DataMetricCard label="MANDATE ID" value={leg.leg_id?.slice(0, 12) + '…'} mono />
              <DataMetricCard label="SKU" value={leg.sku} mono />
              <DataMetricCard label="ITEM" value={leg.name} />
              <DataMetricCard label="AUTHORIZED" value={formatPaise(leg.amount_paise)} />
            </div>
          </div>
        ))}

        <EvidenceDrawer label="RAW PURCHASE PLAN" drawerKey="ch04_raw" isExpanded={expandedDrawers['ch04_raw']} onToggle={toggleDrawer} data={d.plan} copyKey="raw_plan" copiedKey={copiedKey} onCopy={handleCopy} />
      </div>
      <ConduitConnector />

      {/* ═══════ CH05 — RESERVATION ═══════ */}
      <div className="chapter-node" id="chapter-05">
        <ChapterHeader num="05" tag="RESERVE" title="IntentRegistry Accounting" badge={`${reservedPct}% RESERVED`} badgeColor="badge-cyan" />
        <GuaranteeCallout icon={<Lock size={14} />} text="Aggregate multi-merchant exposure locked prior to gateway execution. 0 float error." color="var(--accent-cyan)" />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginTop: '12px' }}>
          {/* Pre-execution */}
          <div style={{ padding: '14px', background: 'var(--bg-recessed)', border: '1px solid var(--border-line)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: '10px' }}>PRE-EXECUTION</div>
            <div className="metric-grid">
              <DataMetricCard label="SPEND CAP" value={formatPaise(preExec.spend_cap_paise)} />
              <DataMetricCard label="RESERVED" value={formatPaise(preExec.reserved_paise)} />
              <DataMetricCard label="CAPTURED" value={formatPaise(preExec.captured_paise)} />
              <DataMetricCard label="AVAILABLE" value={formatPaise(preExec.available_paise)} />
            </div>
          </div>

          {/* Post-execution */}
          <div style={{ padding: '14px', background: 'var(--bg-recessed)', border: '1px solid var(--border-line)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: '10px' }}>POST-EXECUTION</div>
            <div className="metric-grid">
              <DataMetricCard label="RESERVED" value={formatPaise(postExec.reserved_paise)} />
              <DataMetricCard label="CAPTURED" value={formatPaise(postExec.captured_paise)} />
              <DataMetricCard label="RELEASED" value={formatPaise(d.settlement?.released_paise)} />
              <DataMetricCard label="AVAILABLE" value={formatPaise(postExec.available_paise)} />
            </div>
          </div>
        </div>

        {/* Visual bar */}
        <div style={{ marginTop: '14px', height: '24px', background: 'var(--bg-recessed)', border: '1px solid var(--border-line)', position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: `${capturedPct}%`, background: 'var(--accent-terminal)', opacity: 0.7, transition: 'width 0.6s ease' }} />
          <div style={{ position: 'absolute', right: '8px', top: '50%', transform: 'translateY(-50%)', fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-phosphor)', fontWeight: 700 }}>
            {capturedPct}% CAPTURED
          </div>
        </div>

        <EvidenceDrawer label="RAW RESERVATION DATA" drawerKey="ch05_raw" isExpanded={expandedDrawers['ch05_raw']} onToggle={toggleDrawer} data={d.reservation} copyKey="raw_reservation" copiedKey={copiedKey} onCopy={handleCopy} />
      </div>
      <ConduitConnector />

      {/* ═══════ CH06 — JIT REVALIDATION ═══════ */}
      <div className="chapter-node" id="chapter-06">
        <ChapterHeader num="06" tag="REVALIDATE" title="Just-In-Time Pre-Flight" badge={legs.some(l => !l.jit?.passed) ? 'PARTIAL FAIL' : 'ALL CLEAR'} badgeColor={legs.some(l => !l.jit?.passed) ? 'badge-amber' : 'badge-green'} />
        <GuaranteeCallout icon={<FileCheck size={14} />} text="Real-time stock & quote revalidation at the exact moment of execution." color="var(--accent-green)" />

        {legs.map((leg, i) => {
          const jit = leg.jit || {};
          const passed = jit.passed;
          return (
            <div key={leg.mandate_id || i} style={{ marginTop: '12px', padding: '14px', background: 'var(--bg-recessed)', border: `1px solid ${passed ? 'var(--accent-terminal)' : 'var(--accent-red)'}`, borderLeft: `3px solid ${passed ? 'var(--accent-terminal)' : 'var(--accent-red)'}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                <span style={{ fontFamily: 'var(--font-macro)', fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-phosphor)' }}>
                  LEG {String.fromCharCode(65 + i)} — {leg.merchant_name || leg.merchant_id}
                </span>
                <span className={`badge ${passed ? 'badge-green' : 'badge-red'}`}>{jit.verdict || (passed ? 'PROCEED' : 'FAIL')}</span>
              </div>
              <div className="metric-grid">
                <DataMetricCard label="SKU CHECKED" value={jit.sku_checked} mono />
                <DataMetricCard label="IN STOCK" value={jit.in_stock ? 'YES' : 'NO'} />
                <DataMetricCard label="QUOTE VALID" value={jit.quote_valid ? 'YES' : 'NO'} />
                <DataMetricCard label="PRICE DRIFT" value={jit.price_drift_paise != null ? `${jit.price_drift_paise} paise` : '—'} />
              </div>
              {!passed && jit.message && (
                <div style={{ marginTop: '8px', fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--accent-red)', background: 'rgba(255,60,60,0.06)', padding: '8px 10px', border: '1px solid rgba(255,60,60,0.15)' }}>
                  <strong>{jit.error_code}:</strong> {jit.message}
                </div>
              )}
            </div>
          );
        })}

        <EvidenceDrawer label="RAW JIT DATA" drawerKey="ch06_raw" isExpanded={expandedDrawers['ch06_raw']} onToggle={toggleDrawer} data={legs.map(l => l.jit)} copyKey="raw_jit" copiedKey={copiedKey} onCopy={handleCopy} />
      </div>
      <ConduitConnector />

      {/* ═══════ CH07 — EXECUTION ═══════ */}
      <div className="chapter-node" id="chapter-07">
        <ChapterHeader num="07" tag="EXECUTE" title="Independent Leg Execution" badge={`${d.settlement?.successful_legs || 0}/${legs.length} CAPTURED`} badgeColor={d.settlement?.failed_legs ? 'badge-amber' : 'badge-green'} />
        <GuaranteeCallout icon={<Split size={14} />} text="Each leg executed independently. Captured funds from successful legs never reversed." color="var(--accent-cyan)" />

        {legs.map((leg, i) => {
          const isCaptured = leg.final_status === 'PAYMENT_CAPTURED';
          const isReleased = leg.final_status === 'RELEASED';
          return (
            <div key={leg.mandate_id || i} style={{ marginTop: '12px', padding: '14px', background: 'var(--bg-recessed)', border: `1px solid ${isCaptured ? 'var(--accent-terminal)' : isReleased ? 'var(--accent-amber)' : 'var(--border-line)'}`, borderLeft: `3px solid ${isCaptured ? 'var(--accent-terminal)' : isReleased ? 'var(--accent-amber)' : 'var(--border-line)'}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                <span style={{ fontFamily: 'var(--font-macro)', fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-phosphor)' }}>
                  LEG {String.fromCharCode(65 + i)} — {leg.merchant_name || leg.merchant_id}
                </span>
                <span className={`badge ${isCaptured ? 'badge-green' : isReleased ? 'badge-amber' : 'badge-cyan'}`}>{leg.final_status}</span>
              </div>
              <div className="metric-grid">
                <DataMetricCard label="MANDATE ID" value={leg.mandate_id?.slice(0, 12) + '…'} mono />
                <DataMetricCard label="ORDER ID" value={leg.order?.razorpay_order_id || '—'} mono />
                <DataMetricCard label="AUTHORIZED" value={formatPaise(leg.authorized_amount_paise)} />
                <DataMetricCard label="CAPTURED" value={formatPaise(leg.payment?.captured_paise)} />
                {isReleased && <DataMetricCard label="RELEASED" value={formatPaise(leg.released_reservation_paise)} />}
                {leg.payment?.webhook_status && <DataMetricCard label="WEBHOOK" value={leg.payment.webhook_status} />}
              </div>
            </div>
          );
        })}

        <EvidenceDrawer label="RAW EXECUTION DATA" drawerKey="ch07_raw" isExpanded={expandedDrawers['ch07_raw']} onToggle={toggleDrawer} data={legs} copyKey="raw_execution" copiedKey={copiedKey} onCopy={handleCopy} />
      </div>
      <ConduitConnector />

      {/* ═══════ CH08 — SETTLEMENT ═══════ */}
      <div className="chapter-node" id="chapter-08">
        <ChapterHeader num="08" tag="SETTLE" title="Partial Settlement Outcome"
          badge={d.settlement?.plan_status || '—'}
          badgeColor={d.settlement?.plan_status === 'COMPLETE' ? 'badge-green' : 'badge-amber'} />
        <GuaranteeCallout icon={<Database size={14} />}
          text={d.settlement?.plan_status === 'COMPLETE' ? 'All legs captured. Full settlement complete.' : 'Captured funds untouched. Zero false atomicity. No phantom goods.'}
          color={d.settlement?.plan_status === 'COMPLETE' ? 'var(--accent-green)' : 'var(--accent-amber)'} />

        <div className="metric-grid">
          <DataMetricCard label="PLAN STATUS" value={d.settlement?.plan_status} />
          <DataMetricCard label="AUTHORIZED" value={formatPaise(d.settlement?.authorized_paise)} />
          <DataMetricCard label="CAPTURED" value={formatPaise(d.settlement?.captured_paise)} />
          <DataMetricCard label="RELEASED" value={formatPaise(d.settlement?.released_paise)} />
          <DataMetricCard label="AVAILABLE" value={formatPaise(d.settlement?.available_paise)} />
          <DataMetricCard label="SUCCESSFUL LEGS" value={d.settlement?.successful_legs} />
          <DataMetricCard label="FAILED LEGS" value={d.settlement?.failed_legs} />
        </div>

        {/* Visual settlement bar */}
        <div style={{ marginTop: '14px' }}>
          <div style={{ display: 'flex', height: '28px', border: '1px solid var(--border-line)', overflow: 'hidden' }}>
            {d.settlement?.captured_paise > 0 && (
              <div style={{ width: `${pct(d.settlement.captured_paise, d.settlement.authorized_paise)}%`, background: 'var(--accent-terminal)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: '#052414', fontWeight: 700, transition: 'width 0.6s' }}>
                CAPTURED {pct(d.settlement.captured_paise, d.settlement.authorized_paise)}%
              </div>
            )}
            {d.settlement?.released_paise > 0 && (
              <div style={{ width: `${pct(d.settlement.released_paise, d.settlement.authorized_paise)}%`, background: 'var(--accent-amber)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: '#1a1206', fontWeight: 700, transition: 'width 0.6s' }}>
                RELEASED
              </div>
            )}
          </div>
        </div>

        <EvidenceDrawer label="RAW SETTLEMENT DATA" drawerKey="ch08_raw" isExpanded={expandedDrawers['ch08_raw']} onToggle={toggleDrawer} data={d.settlement} copyKey="raw_settlement" copiedKey={copiedKey} onCopy={handleCopy} />
      </div>
      <ConduitConnector />

      {/* ═══════ CH09 — AUDIT PROOF ═══════ */}
      <div className="chapter-node" id="chapter-09">
        <ChapterHeader num="09" tag="AUDIT" title="Hash-Chained Audit Proof" badge={d.audit?.chain_valid ? 'CHAIN VALID' : 'CHAIN BROKEN'} badgeColor={d.audit?.chain_valid ? 'badge-green' : 'badge-red'} />
        <GuaranteeCallout icon={<Terminal size={14} />} text="Every financial state transition permanently sealed in append-only SHA-256 hash chain." color="var(--accent-terminal)" />

        <div className="metric-grid">
          <DataMetricCard label="CHAIN VALID" value={d.audit?.chain_valid ? 'TRUE' : 'FALSE'} />
          <DataMetricCard label="TOTAL BLOCKS" value={d.audit?.total_blocks} />
          <DataMetricCard label="RUN EVENTS" value={events.length} />
        </div>

        {events.length > 0 && (
          <div style={{ marginTop: '12px' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: '6px' }}>RUN-SCOPED LEDGER EVENTS</div>
            <table className="audit-table">
              <thead><tr><th>#</th><th>EVENT TYPE</th><th>HASH</th><th>TIMESTAMP</th></tr></thead>
              <tbody>
                {events.map((ev, i) => (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td><span className="badge badge-cyan">{ev.type}</span></td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6rem' }}>{ev.entry_hash?.slice(0, 16)}…</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6rem' }}>{ev.created_at?.slice(11, 19) || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <EvidenceDrawer label="RAW AUDIT DATA" drawerKey="ch09_raw" isExpanded={expandedDrawers['ch09_raw']} onToggle={toggleDrawer} data={d.audit} copyKey="raw_audit" copiedKey={copiedKey} onCopy={handleCopy} />
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------
// REUSABLE NARRATIVE SUBCOMPONENTS
// ----------------------------------------------------------------------------

function ChapterHeader({ num, tag, title, badge, badgeColor = 'badge-cyan' }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        paddingBottom: '10px',
        borderBottom: '1px solid var(--border-line)',
        marginBottom: '14px',
      }}
    >
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontWeight: 900,
          fontSize: '0.68rem',
          color: 'var(--accent-terminal)',
          letterSpacing: '0.05em',
          flexShrink: 0,
        }}
      >
        {num}
      </span>
      <span
        className={`badge badge-terminal`}
        style={{
          fontFamily: 'var(--font-mono)',
          fontWeight: 800,
          fontSize: '0.55rem',
          letterSpacing: '0.12em',
          flexShrink: 0,
        }}
      >
        {tag}
      </span>
      <span
        style={{
          fontFamily: 'var(--font-macro)',
          fontWeight: 700,
          fontSize: '0.82rem',
          color: 'var(--text-phosphor)',
          flexGrow: 1,
        }}
      >
        {title}
      </span>
      {badge && (
        <span
          className={`badge ${badgeColor}`}
          style={{
            fontFamily: 'var(--font-mono)',
            fontWeight: 800,
            fontSize: '0.55rem',
            letterSpacing: '0.06em',
            flexShrink: 0,
          }}
        >
          {badge}
        </span>
      )}
    </div>
  );
}

function GuaranteeCallout({ icon, text, color = 'var(--accent-cyan)' }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '10px',
        padding: '12px 14px',
        background: `linear-gradient(135deg, ${color}06, transparent)`,
        border: `1px solid ${color}22`,
        borderLeft: `3px solid ${color}`,
        marginBottom: '14px',
        fontFamily: 'var(--font-mono)',
        fontSize: '0.68rem',
        lineHeight: 1.5,
        color: 'var(--text-label)',
      }}
    >
      <span style={{ color, flexShrink: 0, marginTop: '1px' }}>{icon}</span>
      <span>{text}</span>
    </div>
  );
}

function ConduitConnector() {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        padding: '6px 0',
      }}
    >
      <div
        style={{
          width: '2px',
          height: '28px',
          background:
            'repeating-linear-gradient(to bottom, var(--accent-terminal), var(--accent-terminal) 4px, transparent 4px, transparent 8px)',
          opacity: 0.5,
        }}
      />
    </div>
  );
}

function DataMetricCard({ label, value, mono = false }) {
  return (
    <div
      style={{
        padding: '10px 12px',
        background: 'var(--bg-recessed)',
        border: '1px solid var(--border-line)',
        minWidth: '120px',
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.55rem',
          color: 'var(--text-muted)',
          letterSpacing: '0.1em',
          marginBottom: '4px',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: mono ? 'var(--font-mono)' : 'var(--font-macro)',
          fontWeight: mono ? 600 : 700,
          fontSize: '0.78rem',
          color: 'var(--text-phosphor)',
          wordBreak: 'break-all',
        }}
      >
        {value ?? '—'}
      </div>
    </div>
  );
}

function EvidenceDrawer({
  label,
  drawerKey,
  isExpanded,
  onToggle,
  data,
  copyKey,
  copiedKey,
  onCopy,
}) {
  const jsonStr = data ? JSON.stringify(data, null, 2) : '{}';
  return (
    <div
      style={{
        marginTop: '12px',
        border: '1px solid var(--border-line)',
        background: 'var(--bg-recessed)',
      }}
    >
      <button
        onClick={() => onToggle(drawerKey)}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          width: '100%',
          padding: '8px 12px',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.6rem',
          color: 'var(--text-muted)',
          letterSpacing: '0.08em',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <span>
          {isExpanded ? '▼' : '▶'} {label}
        </span>
        {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {isExpanded && (
        <div
          style={{
            padding: '10px 12px',
            borderTop: '1px solid var(--border-line)',
            position: 'relative',
          }}
        >
          <button
            onClick={() => onCopy(jsonStr, copyKey)}
            style={{
              position: 'absolute',
              top: '6px',
              right: '8px',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color:
                copiedKey === copyKey
                  ? 'var(--accent-terminal)'
                  : 'var(--text-muted)',
            }}
          >
            {copiedKey === copyKey ? (
              <Check size={12} />
            ) : (
              <Copy size={12} />
            )}
          </button>
          <pre
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.6rem',
              color: 'var(--text-label)',
              lineHeight: 1.5,
              overflowX: 'auto',
              maxHeight: '320px',
              margin: 0,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {jsonStr}
          </pre>
        </div>
      )}
    </div>
  );
}

import React, { useState, useEffect } from 'react';
import {
  X,
  ShieldCheck,
  Zap,
  Skull,
  Play,
  Terminal,
  FileText,
  Lock,
  ArrowRight,
  RotateCcw,
  CheckCircle2,
  AlertOctagon,
  Layers,
  Minimize2,
  Maximize2,
} from 'lucide-react';

const TAB_CONFIG = {
  pitch: {
    index: 1,
    pace: 'MIN 0:00 – 1:15',
    nextTab: 'trust',
    nextLabel: '02 TRUST RAIL',
    nextShort: 'RAIL',
  },
  trust: {
    index: 2,
    pace: 'MIN 1:15 – 2:30',
    prevTab: 'pitch',
    prevLabel: '01 PITCH',
    prevShort: 'PITCH',
    nextTab: 'threats',
    nextLabel: '03 THREATS',
    nextShort: 'THREAT',
  },
  threats: {
    index: 3,
    pace: 'MIN 2:30 – 3:45',
    prevTab: 'trust',
    prevLabel: '02 TRUST RAIL',
    prevShort: 'RAIL',
    nextTab: 'demo',
    nextLabel: '04 DEMO RUN',
    nextShort: 'DEMO',
  },
  demo: {
    index: 4,
    pace: 'MIN 3:45 – 5:00',
    prevTab: 'threats',
    prevLabel: '03 THREATS',
    prevShort: 'THREAT',
    isLast: true,
  },
};

export default function SpecDrawer({
  isOpen,
  onClose,
  onRunGoldenPurchase,
  onRunAttack,
  onVerifyLedger,
  isExecuting = false,
}) {
  const [activeTab, setActiveTab] = useState('pitch'); // 'pitch' | 'trust' | 'threats' | 'demo'
  const [macroStatus, setMacroStatus] = useState(null);
  const [isCompact, setIsCompact] = useState(false);

  // Keyboard slide progression & hotkeys (ArrowLeft, ArrowRight, 1-4, ESC)
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      // Don't intercept if user is typing in an input or textarea
      const tag = e.target?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target?.isContentEditable) {
        if (e.key === 'Escape') onClose();
        return;
      }

      const TABS = ['pitch', 'trust', 'threats', 'demo'];

      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        setActiveTab((curr) => {
          const idx = TABS.indexOf(curr);
          return idx < TABS.length - 1 ? TABS[idx + 1] : curr;
        });
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        setActiveTab((curr) => {
          const idx = TABS.indexOf(curr);
          return idx > 0 ? TABS[idx - 1] : curr;
        });
      } else if (e.key === '1') {
        e.preventDefault();
        setActiveTab('pitch');
      } else if (e.key === '2') {
        e.preventDefault();
        setActiveTab('trust');
      } else if (e.key === '3') {
        e.preventDefault();
        setActiveTab('threats');
      } else if (e.key === '4') {
        e.preventDefault();
        setActiveTab('demo');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleExecuteMacro = async (macroName, runnerFn) => {
    if (!runnerFn || isExecuting) return;
    setMacroStatus({ name: macroName, status: 'RUNNING' });
    try {
      const res = await runnerFn();
      setMacroStatus({
        name: macroName,
        status: 'SUCCESS',
        summary: res?.message || 'Execution verified on live dashboard.',
      });
    } catch (err) {
      setMacroStatus({
        name: macroName,
        status: 'FAILED',
        summary: err.message,
      });
    }
  };

  const handleResetTourState = () => {
    localStorage.removeItem('mandate_mesh_guide_seen');
    alert('Tour state reset. Drawer will auto-open on next fresh load.');
  };

  return (
    <div
      className={`spec-drawer-backdrop ${isCompact ? 'compact-mode' : ''}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={`spec-drawer-panel ${isCompact ? 'compact' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label="Project Specification & Pitch Deck"
      >
        
        {/* Drawer Header */}
        <div className="spec-drawer-header" style={isCompact ? { padding: '8px 10px' } : {}}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
            <div style={{
              background: 'var(--accent-terminal)',
              color: 'var(--bg-terminal)',
              padding: '2px 5px',
              fontFamily: 'var(--font-mono)',
              fontWeight: 900,
              fontSize: '10px',
              flexShrink: 0,
            }}>
              {isCompact ? 'REM' : 'SPEC'}
            </div>
            <div style={{ overflow: 'hidden' }}>
              <h2 style={{
                fontSize: isCompact ? '0.78rem' : '0.92rem',
                fontFamily: 'var(--font-macro)',
                color: 'var(--text-phosphor)',
                margin: 0,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}>
                {isCompact ? 'MM // CONTROLLER' : 'MANDATE MESH SPEC // PITCH DECK'}
              </h2>
              {!isCompact && (
                <p style={{ fontSize: '0.65rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', margin: 0 }}>
                  5-MIN ARCHITECTURE &amp; DEMO &bull; <span style={{ color: 'var(--text-phosphor)' }}>[KEYS: 1-4 / &larr; &rarr;]</span>
                </p>
              )}
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
            <button
              onClick={() => setIsCompact(!isCompact)}
              className="btn btn-secondary"
              title={isCompact ? 'Expand to Full Deck (560px)' : 'Switch to Compact Remote (320px) for Recording'}
              style={{ padding: '4px 6px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '3px' }}
            >
              {isCompact ? <Maximize2 size={10} /> : <Minimize2 size={10} />}
              <span>{isCompact ? '[ EXP ]' : '[ REM ]'}</span>
            </button>

            <button
              onClick={onClose}
              className="btn btn-secondary"
              title="Dismiss Drawer (ESC)"
              style={{ padding: '4px 6px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '3px' }}
            >
              <span>[ ✕ ]</span>
            </button>
          </div>
        </div>

        {/* 4 Presentation Tabs */}
        <div className="spec-drawer-tabs">
          <button
            className={`spec-drawer-tab ${activeTab === 'pitch' ? 'active' : ''}`}
            onClick={() => setActiveTab('pitch')}
            title="[Key: 1 or ←/→] The Problem & Invariant"
            style={isCompact ? { fontSize: '0.62rem', padding: '6px 2px' } : {}}
          >
            {isCompact ? 'PITCH' : '01: PITCH'}
          </button>
          <button
            className={`spec-drawer-tab ${activeTab === 'trust' ? 'active' : ''}`}
            onClick={() => setActiveTab('trust')}
            title="[Key: 2 or ←/→] 5-Hop Trust Rail Architecture"
            style={isCompact ? { fontSize: '0.62rem', padding: '6px 2px' } : {}}
          >
            {isCompact ? 'RAIL' : '02: TRUST RAIL'}
          </button>
          <button
            className={`spec-drawer-tab ${activeTab === 'threats' ? 'active' : ''}`}
            onClick={() => setActiveTab('threats')}
            title="[Key: 3 or ←/→] Live Attack Demonstrations"
            style={isCompact ? { fontSize: '0.62rem', padding: '6px 2px' } : {}}
          >
            {isCompact ? 'THREAT' : '03: THREATS'}
          </button>
          <button
            className={`spec-drawer-tab ${activeTab === 'demo' ? 'active' : ''}`}
            onClick={() => setActiveTab('demo')}
            title="[Key: 4 or ←/→] 1-Click Interactive Demo Run"
            style={isCompact ? { fontSize: '0.62rem', padding: '6px 2px' } : {}}
          >
            {isCompact ? 'DEMO' : '04: DEMO RUN'}
          </button>
        </div>

        {/* Drawer Scrollable Body */}
        <div className="spec-drawer-body" style={isCompact ? { padding: '10px', gap: '10px' } : {}}>
          
          {/* ============================================================== */}
          {/* TAB 1: PITCH (THE PROBLEM & CORE INVARIANT)                     */}
          {/* ============================================================== */}
          {activeTab === 'pitch' && (
            <>
              <div className="spec-card" style={{ borderColor: 'var(--accent-red)' }}>
                <div className="spec-card-title" style={{ color: 'var(--accent-red)' }}>
                  <AlertOctagon size={14} />
                  <span>THE $100B AUTONOMOUS VULNERABILITY</span>
                </div>
                <p style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                  Autonomous LLM agents are rapidly gaining internet purchasing power. However, LLMs are non-deterministic, hallucinatory, and susceptible to prompt injections. Giving an AI model raw payment credentials or API keys is catastrophic.
                </p>
              </div>

              <div className="spec-card" style={{ borderColor: 'var(--accent-terminal)' }}>
                <div className="spec-card-title" style={{ color: 'var(--accent-terminal)' }}>
                  <ShieldCheck size={14} />
                  <span>THE MANDATE MESH THESIS</span>
                </div>
                <div style={{
                  background: 'var(--bg-terminal)',
                  border: '1px solid var(--border-bright)',
                  padding: '8px 10px',
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 700,
                  fontSize: '0.8rem',
                  color: 'var(--text-phosphor)',
                  textAlign: 'center',
                }}>
                  "LLM PROPOSES, DETERMINISTIC PYTHON DISPOSES"
                </div>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                  The agent acts exclusively as an untrusted recommendation engine. Every rupee movement is gated by deterministic Python validation, signed carts, and hard mathematical constraints.
                </p>
              </div>

              <div className="spec-card">
                <div className="spec-card-title">
                  <Lock size={14} color="var(--accent-steel)" />
                  <span>3 MATHEMATICAL GUARANTEES</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.72rem' }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                    <span style={{ color: 'var(--accent-terminal)', fontWeight: 700 }}>01.</span>
                    <div>
                      <strong style={{ color: 'var(--text-phosphor)' }}>Zero Floating-Point Arithmetic:</strong>
                      <p style={{ color: 'var(--text-muted)' }}>100% integer paise accounting across quotes, mandates, webhooks, and ledger entries.</p>
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                    <span style={{ color: 'var(--accent-terminal)', fontWeight: 700 }}>02.</span>
                    <div>
                      <strong style={{ color: 'var(--text-phosphor)' }}>Dual-Layer Content Integrity:</strong>
                      <p style={{ color: 'var(--text-muted)' }}>ECDSA P-256 JWT signature from merchants paired with canonical SHA-256 cart content digests.</p>
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                    <span style={{ color: 'var(--accent-terminal)', fontWeight: 700 }}>03.</span>
                    <div>
                      <strong style={{ color: 'var(--text-phosphor)' }}>Linear Hash-Chained Audit Ledger:</strong>
                      <p style={{ color: 'var(--text-muted)' }}>Every payment event links cryptographically to the previous block hash via advisory/row-locked consistency.</p>
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* ============================================================== */}
          {/* TAB 2: TRUST RAIL (5-HOP CRYPTOGRAPHIC SEQUENCE)                */}
          {/* ============================================================== */}
          {activeTab === 'trust' && (
            <>
              <div className="spec-card">
                <div className="spec-card-title">
                  <Layers size={14} color="var(--accent-terminal)" />
                  <span>THE 5-LAYER CRYPTOGRAPHIC RAIL</span>
                </div>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                  A transaction must pass through 5 deterministic validation gates before funds are captured:
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0px', marginTop: '6px', position: 'relative' }}>
                  <div style={{
                    position: 'absolute',
                    left: '26px',
                    top: '12px',
                    bottom: '12px',
                    width: '1px',
                    background: 'var(--border-line)',
                    zIndex: 0,
                  }} />
                  {[
                    { hop: 'HOP 1', label: 'User Purchasing Intent', desc: 'Goal definition with spend ceiling and merchant allowlist.' },
                    { hop: 'HOP 2', label: 'LangGraph Deliberation', desc: 'Agent compares candidate quotes; generates draft basket.' },
                    { hop: 'HOP 3', label: 'Merchant Cart Signature', desc: 'Merchant signs cart with ECDSA P-256 (cart_jwt) + SHA-256 digest.' },
                    { hop: 'HOP 4', label: 'Mandate Authorization', desc: 'Deterministic Python checks signatures, limits, & registers Razorpay order.' },
                    { hop: 'HOP 5', label: 'Webhook & Ledger Settled', desc: 'HMAC-verified capture locks mandate and writes to tamper-evident chain.' },
                  ].map((h, idx) => (
                    <div
                      key={idx}
                      style={{
                        background: 'var(--bg-terminal)',
                        border: '1px solid var(--border-line)',
                        marginBottom: idx < 4 ? '6px' : '0',
                        padding: '6px 8px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        fontSize: '0.7rem',
                        position: 'relative',
                        zIndex: 1,
                      }}
                    >
                      <span className="badge badge-steel" style={{ fontSize: '0.6rem', minWidth: '42px', textAlign: 'center', background: 'var(--bg-surface)' }}>
                        {h.hop}
                      </span>
                      <div style={{ flex: 1 }}>
                        <div style={{ color: 'var(--text-phosphor)', fontWeight: 700 }}>{h.label}</div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.64rem' }}>{h.desc}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="spec-card">
                <div className="spec-card-title">
                  <Terminal size={14} color="var(--text-secondary)" />
                  <span>MANDATE DATA INVARIANT CONTRACT</span>
                </div>
                <div className="spec-code-well">
{`{
  "mandate_id": "man_3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "intent_hash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "cart_hash": "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
  "authorized_amount_paise": 124900,
  "currency": "INR",
  "razorpay_order_id": "order_EKfUsjfhp69Rvg",
  "status": "AUTHORIZED"
}`}
                </div>
              </div>
            </>
          )}

          {/* ============================================================== */}
          {/* TAB 3: THREAT MATRIX (6 ADVERSARIAL VECTORS)                    */}
          {/* ============================================================== */}
          {activeTab === 'threats' && (
            <>
              <div className="spec-card" style={{ borderColor: 'var(--accent-red)' }}>
                <div className="spec-card-title" style={{ color: 'var(--accent-red)' }}>
                  <Skull size={14} />
                  <span>THE 6-VECTOR THREAT DEFENSE MATRIX</span>
                </div>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                  Every vector is actively simulated on the Adversarial Threat Bench. All vectors fail closed with 0 unauthorized rupees moved:
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px' }}>
                  {[
                    { tag: '01: OVER-SPEND', vector: 'Budget Escalation Attack', intercept: 'HTTP 403 · POLICY_SPEND_CAP_EXCEEDED' },
                    { tag: '02: INJECTION', vector: 'Prompt Injection Fake SKU', intercept: 'HTTP 404 · CATALOG_SKU_NOT_FOUND' },
                    { tag: '03: MITM TAMPER', vector: 'Cart Price Modification', intercept: 'HTTP 409 · POLICY_CART_SIGNATURE_INVALID' },
                    { tag: '04: REPLAY', vector: 'Idempotent Webhook Replay (3x)', intercept: 'HTTP 200 · DEDUPLICATED (0 Double Debits)' },
                    { tag: '05: KEY FORGERY', vector: 'Cross-Merchant Key Forgery', intercept: 'HTTP 409 · POLICY_CART_SIGNATURE_INVALID' },
                    { tag: '06: EXPIRED TTL', vector: 'Stale Quote Replay Attack', intercept: 'HTTP 409 · POLICY_CART_EXPIRED' },
                  ].map((item, idx) => (
                    <div
                      key={idx}
                      style={{
                        background: 'var(--bg-terminal)',
                        border: '1px solid var(--border-line)',
                        padding: '6px 8px',
                        display: 'flex',
                        flexDirection: isCompact ? 'column' : 'row',
                        alignItems: isCompact ? 'flex-start' : 'center',
                        justifyContent: 'space-between',
                        gap: isCompact ? '4px' : '8px',
                        fontSize: '0.7rem',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ color: 'var(--accent-red)', fontWeight: 700, whiteSpace: 'nowrap' }}>
                          [{item.tag}]
                        </span>
                        <span style={{ color: 'var(--text-phosphor)', fontWeight: 600 }}>{item.vector}</span>
                      </div>
                      <span
                        className="badge badge-red"
                        style={{
                          fontSize: '0.62rem',
                          alignSelf: isCompact ? 'stretch' : 'auto',
                          textAlign: isCompact ? 'center' : 'right',
                        }}
                      >
                        {item.intercept}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* ============================================================== */}
          {/* TAB 4: DEMO CONTROLLER (LIVE PRESENTATION MACROS)               */}
          {/* ============================================================== */}
          {activeTab === 'demo' && (
            <>
              <div className="spec-card" style={{ borderColor: 'var(--accent-terminal)' }}>
                <div className="spec-card-title" style={{ color: 'var(--accent-terminal)' }}>
                  <Play size={14} />
                  <span>5-MINUTE LIVE DEMO RUNBOOK</span>
                </div>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                  Execute these macros directly during your video recording. Each action runs against the live FastAPI backend and updates the background dashboard live on camera:
                </p>

                {/* Macro 1: Golden Path */}
                <div style={{
                  background: 'var(--bg-terminal)',
                  border: '1px solid var(--border-line)',
                  padding: '10px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, color: 'var(--accent-terminal)', fontSize: '0.74rem' }}>
                      STEP 1: GOLDEN AUTONOMOUS PURCHASE
                    </span>
                    <span className="badge badge-green" style={{ fontSize: '0.6rem' }}>HAPPY PATH</span>
                  </div>
                  <p style={{ fontSize: '0.68rem', color: 'var(--text-muted)', margin: 0 }}>
                    Orders a 1kg chocolate cake under ₹1,500. Demonstrates quote comparison, ECDSA signed cart, and mandate issuance.
                  </p>
                  <button
                    className="btn btn-primary"
                    onClick={() => handleExecuteMacro('Golden Purchase', onRunGoldenPurchase)}
                    disabled={isExecuting}
                    style={{ fontSize: '0.72rem', padding: '6px 10px', marginTop: '4px' }}
                  >
                    {isExecuting ? 'EXECUTING ON BACKEND...' : '[ 1. RUN GOLDEN PURCHASE ▶ ]'}
                  </button>
                </div>

                {/* Macro 2: Prompt Injection */}
                <div style={{
                  background: 'var(--bg-terminal)',
                  border: '1px solid var(--border-line)',
                  padding: '10px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, color: 'var(--accent-red)', fontSize: '0.74rem' }}>
                      STEP 2: SIMULATE PROMPT INJECTION
                    </span>
                    <span className="badge badge-red" style={{ fontSize: '0.6rem' }}>ATTACK BENCH</span>
                  </div>
                  <p style={{ fontSize: '0.68rem', color: 'var(--text-muted)', margin: 0 }}>
                    Simulates malicious agent prompt ordering fake SKU (`GOLD-COIN`). Confirms deterministic 404 block and 0 rupees moved.
                  </p>
                  <button
                    className="btn btn-danger"
                    onClick={() => handleExecuteMacro('Prompt Injection', onRunAttack)}
                    disabled={isExecuting}
                    style={{ fontSize: '0.72rem', padding: '6px 10px', marginTop: '4px' }}
                  >
                    {isExecuting ? 'TESTING DEFENSE...' : '[ 2. SIMULATE PROMPT INJECTION ⚡ ]'}
                  </button>
                </div>

                {/* Macro 3: Audit Ledger Proof */}
                <div style={{
                  background: 'var(--bg-terminal)',
                  border: '1px solid var(--border-line)',
                  padding: '10px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, color: 'var(--text-phosphor)', fontSize: '0.74rem' }}>
                      STEP 3: AUDIT LEDGER INTEGRITY
                    </span>
                    <span className="badge badge-steel" style={{ fontSize: '0.6rem' }}>SHA-256 CHAIN</span>
                  </div>
                  <p style={{ fontSize: '0.68rem', color: 'var(--text-muted)', margin: 0 }}>
                    Recalculates parent-hash continuity across all database transactions. Verifies 100% linear consistency.
                  </p>
                  <button
                    className="btn btn-secondary"
                    onClick={() => handleExecuteMacro('Audit Chain', onVerifyLedger)}
                    disabled={isExecuting}
                    style={{ fontSize: '0.72rem', padding: '6px 10px', marginTop: '4px' }}
                  >
                    {isExecuting ? 'VERIFYING CHAIN...' : '[ 3. AUDIT HASH CHAIN ✓ ]'}
                  </button>
                </div>
              </div>

              {/* Macro Execution Diagnostic Status */}
              {macroStatus && (
                <div style={{
                  background: 'var(--bg-recessed)',
                  border: `1px solid ${macroStatus.status === 'SUCCESS' ? 'var(--accent-terminal)' : macroStatus.status === 'RUNNING' ? 'var(--accent-amber)' : 'var(--accent-red)'}`,
                  padding: '8px 10px',
                  fontSize: '0.7rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, color: 'var(--text-phosphor)' }}>
                      MACRO: {macroStatus.name}
                    </span>
                    <span className={`badge ${macroStatus.status === 'SUCCESS' ? 'badge-green' : macroStatus.status === 'RUNNING' ? 'badge-amber' : 'badge-red'}`} style={{ fontSize: '0.62rem' }}>
                      {macroStatus.status}
                    </span>
                  </div>
                  {macroStatus.summary && (
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.68rem' }}>
                      {macroStatus.summary}
                    </div>
                  )}
                </div>
              )}
            </>
          )}

        </div>

        {/* Unified Persistent Presentation Console */}
        <div className="spec-drawer-footer">
          <div className="spec-footer-pace">
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ color: 'var(--text-muted)' }}>PACE:</span>
              <span style={{ color: 'var(--accent-terminal)', fontWeight: 700 }}>
                {TAB_CONFIG[activeTab]?.pace}
              </span>
            </div>
            <span style={{ color: 'var(--text-secondary)' }}>
              SLIDE {TAB_CONFIG[activeTab]?.index}/4
            </span>
          </div>

          <div className="spec-footer-actions">
            <button
              onClick={handleResetTourState}
              className="btn btn-secondary"
              title="Clear localStorage to re-test first-time visitor auto-open"
              style={{ fontSize: '0.62rem', padding: '6px 8px', color: 'var(--text-muted)', flexShrink: 0 }}
            >
              <RotateCcw size={10} style={{ marginRight: '2px' }} />
              <span>{isCompact ? 'RESET' : 'RESET TOUR'}</span>
            </button>

            {TAB_CONFIG[activeTab]?.prevTab && (
              <button
                className="btn btn-secondary"
                onClick={() => setActiveTab(TAB_CONFIG[activeTab].prevTab)}
                style={{ flex: 1, fontSize: '0.7rem', padding: '6px 8px' }}
                title="Previous slide (ArrowLeft)"
              >
                {isCompact ? `[ ← ${TAB_CONFIG[activeTab].prevShort} ]` : `[ ← ${TAB_CONFIG[activeTab].prevLabel} ]`}
              </button>
            )}

            {!TAB_CONFIG[activeTab]?.isLast ? (
              <button
                className="btn btn-primary"
                onClick={() => setActiveTab(TAB_CONFIG[activeTab].nextTab)}
                style={{ flex: 1.5, fontSize: '0.7rem', padding: '6px 8px' }}
                title="Next slide (ArrowRight)"
              >
                {isCompact ? `[ NEXT: ${TAB_CONFIG[activeTab].nextShort} → ]` : `[ NEXT: ${TAB_CONFIG[activeTab].nextLabel} → ]`}
              </button>
            ) : (
              <button
                className="btn btn-success"
                onClick={onClose}
                style={{ flex: 1.8, fontSize: '0.7rem', padding: '6px 10px' }}
                title="Complete tour and explore dashboard (ESC or Enter)"
              >
                {isCompact ? '[ DASHBOARD ↵ ]' : '[ ENTER DASHBOARD & EXPLORE ↵ ]'}
              </button>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}

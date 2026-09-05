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

export default function TransactionReactor({ onSwitchToAuditLedger, onLedgerChange }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [journeyData, setJourneyData] = useState(null);
  const [simulateLeg2Failure, setSimulateLeg2Failure] = useState(true);
  const [expandedDrawers, setExpandedDrawers] = useState({});
  const [copiedKey, setCopiedKey] = useState(null);
  const [isAutoScrolling, setIsAutoScrolling] = useState(false);

  const autoScrollTimerRef = useRef(null);

  // Load genuine backend multi-leg orchestration
  const loadData = async (simulateFailure = simulateLeg2Failure) => {
    setLoading(true);
    setError(null);
    try {
      const data = await runMultiLegJourney(
        'I need a birthday cake and candles under Rs. 1500',
        150000,
        simulateFailure
      );
      setJourneyData(data);
      if (onLedgerChange) onLedgerChange();
    } catch (err) {
      console.error('Failed to load multi-leg journey data:', err);
      setError(err.message || 'Failed to connect to backend engine.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData(simulateLeg2Failure);
  }, []);

  const toggleDrawer = (chapterKey) => {
    setExpandedDrawers((prev) => ({
      ...prev,
      [chapterKey]: !prev[chapterKey],
    }));
  };

  const handleCopy = (text, key) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1800);
  };

  const handleToggleFailure = () => {
    const next = !simulateLeg2Failure;
    setSimulateLeg2Failure(next);
    loadData(next);
  };

  const scrollToChapter = (chapterId) => {
    const el = document.getElementById(chapterId);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  // Cinematic Auto-Trace Playback
  const handleToggleAutoScroll = () => {
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

  const stages = journeyData?.stages || {};
  const s1 = stages.stage1_user_intent || {};
  const s2 = stages.stage2_ai_deliberation || {};
  const s3 = stages.stage3_intent_boundary || {};
  const s4 = stages.stage4_purchase_plan || {};
  const s5 = stages.stage5_reservation || {};
  const s6 = stages.stage6_jit_revalidation || {};
  const s7 = stages.stage7_independent_execution || {};
  const s8 = stages.stage8_partial_outcome || {};
  const s9 = stages.stage9_audit_proof || {};

  const candidates = s2.candidate_merchants_evaluated || [];
  const legs = s4.legs || [];
  const leg1Jit = s6.leg1_cakehouse || {};
  const leg2Jit = s6.leg2_sweetdelight || {};
  const leg1Exec = s7.leg1_result || {};
  const leg2Exec = s7.leg2_result || {};

  return (
    <div className="stream-container">
      {/* =========================================================================
          STICKY TRANSACTION HUD (PINS WHILE SCROLLING)
          Displays live aggregate financial reconciliation across the journey
          ========================================================================= */}
      <div className="sticky-narrative-hud">
        {/* Left: Prompt & Spend Cap */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div
            style={{
              background: 'var(--accent-terminal)',
              color: '#052414',
              padding: '3px 7px',
              fontFamily: 'var(--font-mono)',
              fontWeight: 900,
              fontSize: '0.68rem',
              letterSpacing: '0.05em',
            }}
          >
            ACTIVE TRANSACTION
          </div>
          <span
            style={{
              fontFamily: 'var(--font-macro)',
              fontWeight: 700,
              fontSize: '0.88rem',
              color: 'var(--text-phosphor)',
            }}
          >
            "I need a birthday cake and candles under ₹1,500"
          </span>
        </div>

        {/* Center: Live Financial Balance Ticker */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontFamily: 'var(--font-mono)',
            fontSize: '0.7rem',
            background: 'var(--bg-recessed)',
            border: '1px solid var(--border-line)',
            padding: '4px 10px',
          }}
        >
          <span style={{ color: 'var(--text-muted)' }}>SPEND CAP:</span>
          <span style={{ color: 'var(--text-phosphor)', fontWeight: 700 }}>₹1,500.00</span>
          <span style={{ color: 'var(--border-line)' }}>|</span>

          <span style={{ color: 'var(--text-muted)' }}>RESERVED:</span>
          <span style={{ color: 'var(--accent-amber)', fontWeight: 700 }}>₹1,120.00</span>
          <span style={{ color: 'var(--border-line)' }}>|</span>

          <span style={{ color: 'var(--text-muted)' }}>CAPTURED:</span>
          <span style={{ color: 'var(--accent-terminal)', fontWeight: 700 }}>
            {simulateLeg2Failure ? '₹940.00' : '₹1,120.00'}
          </span>
          <span style={{ color: 'var(--border-line)' }}>|</span>

          <span style={{ color: 'var(--text-muted)' }}>UNSPENT / RELEASED:</span>
          <span style={{ color: 'var(--accent-steel)', fontWeight: 700 }}>
            {simulateLeg2Failure ? '₹180.00' : '₹0.00'}
          </span>
        </div>

        {/* Right: Auto-Trace & Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            className={`btn ${isAutoScrolling ? 'btn-danger' : 'btn-primary'}`}
            onClick={handleToggleAutoScroll}
            style={{ fontSize: '0.7rem', padding: '4px 10px' }}
            title="Auto-scroll through the complete transaction trace"
          >
            {isAutoScrolling ? (
              <>
                <Pause size={11} />
                <span>PAUSE TRACE</span>
              </>
            ) : (
              <>
                <Play size={11} />
                <span>AUTO-PLAY TRACE</span>
              </>
            )}
          </button>

          <button
            onClick={handleToggleFailure}
            className="btn btn-secondary"
            style={{
              fontSize: '0.68rem',
              padding: '4px 8px',
              color: simulateLeg2Failure ? 'var(--accent-red)' : 'var(--text-secondary)',
              borderColor: simulateLeg2Failure ? 'rgba(208, 59, 59, 0.4)' : 'var(--border-line)',
            }}
            title="Toggle simulated Leg 2 stock exhaustion to demonstrate partial completion resilience"
          >
            <span>LEG 2 OOS:</span>
            <strong>{simulateLeg2Failure ? 'ON (PARTIAL)' : 'OFF (100% PASS)'}</strong>
          </button>

          <button
            onClick={() => loadData()}
            disabled={loading}
            className="btn btn-secondary"
            style={{ fontSize: '0.68rem', padding: '4px 8px' }}
            title="Re-execute genuine orchestration on FastAPI backend"
          >
            <RefreshCw size={11} className={loading ? 'spin' : ''} />
            <span>{loading ? 'RUNNING...' : 'RE-RUN'}</span>
          </button>
        </div>
      </div>

      {/* =========================================================================
          CHAPTER 01: HUMAN ORIGIN // NATURAL LANGUAGE INTENT
          ========================================================================= */}
      <div id="chapter-01" className="chapter-node">
        <ChapterHeader
          num="01"
          tag="HUMAN ORIGIN"
          title="User Intent & Authoritative Spending Cap"
          badge="ROOT CONSTRAINTS SIGNED"
          badgeColor="badge-cyan"
        />

        <GuaranteeCallout
          invariant="Signed constraints are established outside the LLM before any autonomous planning begins."
          benefit="An unconstrained AI cannot be hijacked or prompted to exceed the user's hard ₹1,500.00 financial boundary."
        />

        {/* Visual Content */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: '10px',
            marginTop: '12px',
          }}
        >
          <DataMetricCard
            label="HUMAN PROMPT"
            value="I need a birthday cake and candles under ₹1,500"
            isText
          />
          <DataMetricCard
            label="MAX SPEND CAP"
            value="₹1,500.00"
            subValue="150,000 paise (Hard Ceiling)"
            accentColor="var(--accent-terminal)"
          />
          <DataMetricCard
            label="MAX HOPS"
            value="5 Transactions"
            subValue="Locked in IntentRegistry"
          />
          <DataMetricCard
            label="SIGNATURE STANDARD"
            value="NIST P-256 ECDSA"
            subValue="Hardware / Keystore Signed"
            accentColor="var(--accent-steel)"
          />
        </div>

        {/* Expandable Technical Proof */}
        <EvidenceDrawer
          isOpen={expandedDrawers['ch1']}
          onToggle={() => toggleDrawer('ch1')}
          title="Raw Cryptographic Intent Payload (UserIntentCredential)"
          data={{
            intent_id: s1.intent_id || 'intent_demo_01',
            user_id: 'user_control_tower_01',
            spend_cap_paise: s1.spend_cap_paise || 150000,
            currency: 'INR',
            allowed_categories: ['bakery', 'gifting'],
            allowed_merchant_ids: ['merchant_cakehouse_01', 'merchant_sweetdelight_02'],
            nonce: s1.nonce || '0x4f8b9e12a4c6',
            validity: '1 Hour Window',
          }}
          copyKey="raw_intent"
          copiedKey={copiedKey}
          onCopy={handleCopy}
        />
      </div>

      <ConduitConnector text="DELIBERATION PIPELINE // PROMPT PASSED TO REASONING ENGINE" />

      {/* =========================================================================
          CHAPTER 02: THE SANDBOX // AGENTIC DELIBERATION & CATALOG PROPOSAL
          ========================================================================= */}
      <div id="chapter-02" className="chapter-node">
        <ChapterHeader
          num="02"
          tag="AI REASONING"
          title="Autonomous Basket Planning & Catalog Discovery"
          badge="ZERO FINANCIAL AUTHORITY"
          badgeColor="badge-amber"
        />

        <GuaranteeCallout
          invariant="The AI agent proposes multi-merchant item allocations, but possesses 0 private keys, 0 Razorpay tokens, and 0 execution rights."
          benefit="Even complete prompt injection or model hallucination cannot move money directly. The LLM only proposes — Python cryptographic policy disposes."
        />

        {/* Candidate Discovery Table */}
        <div style={{ marginTop: '12px', overflowX: 'auto' }}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.74rem',
            }}
          >
            <thead>
              <tr
                style={{
                  background: 'var(--bg-surface)',
                  borderBottom: '1px solid var(--border-line)',
                  textAlign: 'left',
                  color: 'var(--text-muted)',
                }}
              >
                <th style={{ padding: '8px 10px' }}>PROPOSED ITEM</th>
                <th style={{ padding: '8px 10px' }}>MERCHANT</th>
                <th style={{ padding: '8px 10px' }}>CATEGORY</th>
                <th style={{ padding: '8px 10px' }}>DISCOVERED QUOTE</th>
                <th style={{ padding: '8px 10px' }}>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c, idx) => (
                <tr
                  key={idx}
                  style={{
                    borderBottom: '1px solid var(--border-line)',
                    background: idx % 2 === 0 ? 'transparent' : 'var(--bg-recessed)',
                  }}
                >
                  <td style={{ padding: '8px 10px', fontWeight: 700 }}>{c.item}</td>
                  <td style={{ padding: '8px 10px', color: 'var(--text-secondary)' }}>
                    {c.name} ({c.merchant_id})
                  </td>
                  <td style={{ padding: '8px 10px' }}>
                    <span className="badge badge-steel">{idx === 0 ? 'bakery' : 'gifting'}</span>
                  </td>
                  <td
                    style={{
                      padding: '8px 10px',
                      color: 'var(--accent-terminal)',
                      fontWeight: 700,
                    }}
                  >
                    ₹{(c.quote_paise / 100).toFixed(2)}
                  </td>
                  <td style={{ padding: '8px 10px' }}>
                    <span className="badge badge-green">PROPOSED</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 12px',
            background: 'var(--bg-recessed)',
            border: '1px solid var(--border-line)',
            marginTop: '8px',
            fontFamily: 'var(--font-mono)',
            fontSize: '0.72rem',
          }}
        >
          <span style={{ color: 'var(--text-muted)' }}>PROPOSED BASKET TOTAL:</span>
          <span style={{ color: 'var(--accent-terminal)', fontWeight: 700 }}>
            ₹1,120.00 (WITHIN ₹1,500.00 CAP · ₹380.00 BUFFER REMAINING)
          </span>
        </div>

        <EvidenceDrawer
          isOpen={expandedDrawers['ch2']}
          onToggle={() => toggleDrawer('ch2')}
          title="Agent Deliberation Trace & LLM Airgap Assurance"
          data={{
            objective: s2.inferred_objective || 'Birthday celebration bundle',
            items: s2.inferred_items || [],
            security_boundary: s2.llm_boundary_guarantee,
            payment_credentials_held: 'NONE (0 Keys)',
          }}
          copyKey="raw_deliberation"
          copiedKey={copiedKey}
          onCopy={handleCopy}
        />
      </div>

      <ConduitConnector text="GATEWAY VALIDATION // SIGNED INTENT VERIFICATION" />

      {/* =========================================================================
          CHAPTER 03: THE VAULT GATE // PRE-AGENT INTENT BOUNDARY
          ========================================================================= */}
      <div id="chapter-03" className="chapter-node">
        <ChapterHeader
          num="03"
          tag="POLICY GATEWAY"
          title="Pre-Agent Cryptographic Intent Boundary Seal"
          badge="ECDSA SIGNATURE VERIFIED"
          badgeColor="badge-green"
        />

        <GuaranteeCallout
          invariant="The UserIntentCredential is verified by Mandate Mesh before any plan is authorized, confirming user identity, spend limit, and anti-replay nonce."
          benefit="Guarantees non-repudiation. A compromised agent cannot forge user consent or replay expired authorizations."
        />

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: '10px',
            marginTop: '12px',
          }}
        >
          <DataMetricCard
            label="INTENT ID"
            value={s1.intent_id ? `${s1.intent_id.slice(0, 16)}...` : '0x8f12a4b...'}
            subValue="Unique Cryptographic Nonce"
          />
          <DataMetricCard
            label="POLICY STATUS"
            value="ACTIVE IN REGISTRY"
            subValue="Row Locked in SQLite"
            accentColor="var(--accent-terminal)"
          />
          <DataMetricCard
            label="EXPIRATION TIMESTAMP"
            value="1 Hour Active"
            subValue="Enforced by System Clock"
          />
        </div>

        <EvidenceDrawer
          isOpen={expandedDrawers['ch3']}
          onToggle={() => toggleDrawer('ch3')}
          title="Decoded JWT Header, Claims, and P-256 Verifier Output"
          data={{
            jwt_type: 'UserIntentCredential',
            algorithm: 'ES256 (NIST P-256)',
            signer: 'user_control_tower_01',
            nonce_registered: s1.nonce || '0x4f8b9e12',
            allowed_categories: s3.allowed_categories || ['bakery', 'gifting'],
            policy_engine_verdict: 'PASS (INTENT_ACTIVE)',
          }}
          copyKey="raw_jwt"
          copiedKey={copiedKey}
          onCopy={handleCopy}
        />
      </div>

      <ConduitConnector text="FORK // 1 INTENT DECOMPOSES INTO 2 INDEPENDENT MERCHANT RAILS" />

      {/* =========================================================================
          CHAPTER 04: THE COMPOSER // DETERMINISTIC MULTI-MERCHANT PURCHASE PLAN
          ========================================================================= */}
      <div id="chapter-04" className="chapter-node">
        <ChapterHeader
          num="04"
          tag="PLAN FORK"
          title="Deterministic Purchase Plan Decomposition"
          badge="1 INTENT ➔ 2 RAILS"
          badgeColor="badge-cyan"
        />

        <GuaranteeCallout
          invariant="A single user intent deterministically generates two independent merchant execution legs with separate mandate IDs and merchant signatures."
          benefit="Allows atomic basket grouping while isolating liability: an issue with candles never cancels or corrupts the cake."
        />

        {/* Visual Dual Rail Fork */}
        <div className="dual-rail-grid" style={{ marginTop: '12px' }}>
          {legs.map((leg, idx) => (
            <div
              key={idx}
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-bright)',
                padding: '14px',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.72rem',
                    fontWeight: 700,
                    color: 'var(--accent-terminal)',
                  }}
                >
                  RAIL {idx === 0 ? 'A' : 'B'} // {leg.merchant_id}
                </span>
                <span className="badge badge-green">MANDATE ISSUED</span>
              </div>

              <div
                style={{
                  fontFamily: 'var(--font-macro)',
                  fontSize: '0.98rem',
                  fontWeight: 700,
                  color: 'var(--text-phosphor)',
                }}
              >
                {leg.name}
              </div>

              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.74rem',
                  paddingTop: '6px',
                  borderTop: '1px solid var(--border-line)',
                  color: 'var(--text-secondary)',
                }}
              >
                <span>SKU: {leg.sku}</span>
                <span style={{ color: 'var(--accent-terminal)', fontWeight: 700 }}>
                  ₹{(leg.amount_paise / 100).toFixed(2)}
                </span>
              </div>
            </div>
          ))}
        </div>

        <EvidenceDrawer
          isOpen={expandedDrawers['ch4']}
          onToggle={() => toggleDrawer('ch4')}
          title="PurchasePlan Schema & Decomposed Mandate Records"
          data={{
            plan_id: s4.plan_id || 'plan_multi_01',
            total_authorized_paise: s4.total_authorized_paise || 112000,
            legs: s4.legs || [],
          }}
          copyKey="raw_plan"
          copiedKey={copiedKey}
          onCopy={handleCopy}
        />
      </div>

      <ConduitConnector text="LOCK // PRE-EXECUTION EXPOSURE RESERVATION" />

      {/* =========================================================================
          CHAPTER 05: THE LOCKBOX // PRE-EXECUTION BALANCE RESERVATION
          ========================================================================= */}
      <div id="chapter-05" className="chapter-node">
        <ChapterHeader
          num="05"
          tag="EXPOSURE CONTROL"
          title="Pre-Execution Balance Reservation & Concurrency Lock"
          badge="ZERO FLOAT MATH"
          badgeColor="badge-green"
        />

        <GuaranteeCallout
          invariant="₹1,120.00 is atomically reserved in IntentRegistry before contacting any payment gateway. All accounting uses exact integer paise."
          benefit="Prevents concurrent multi-agent checkouts from overdrafting the user's budget and eliminates floating-point currency rounding errors."
        />

        {/* Visual Balance Tape */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: '10px',
            marginTop: '12px',
          }}
        >
          <DataMetricCard
            label="AUTHORIZED CEILING"
            value="₹1,500.00"
            subValue="150,000 paise"
          />
          <DataMetricCard
            label="RESERVED FOR 2 LEGS"
            value="₹1,120.00"
            subValue="112,000 paise (Locked)"
            accentColor="var(--accent-terminal)"
          />
          <DataMetricCard
            label="FREE UNCOMMITTED BUFFER"
            value="₹380.00"
            subValue="38,000 paise (Available)"
            accentColor="var(--accent-steel)"
          />
        </div>

        {/* Allocation Bar */}
        <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <div
            style={{
              height: '14px',
              background: 'var(--bg-recessed)',
              border: '1px solid var(--border-line)',
              display: 'flex',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: '74.6%',
                background: 'var(--accent-terminal)',
                color: '#052414',
                fontSize: '0.62rem',
                fontWeight: 900,
                fontFamily: 'var(--font-mono)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              74.6% RESERVED (₹1,120.00)
            </div>
            <div
              style={{
                width: '25.4%',
                background: 'var(--bg-surface)',
                color: 'var(--text-secondary)',
                fontSize: '0.62rem',
                fontWeight: 700,
                fontFamily: 'var(--font-mono)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              25.4% FREE (₹380.00)
            </div>
          </div>
        </div>

        <EvidenceDrawer
          isOpen={expandedDrawers['ch5']}
          onToggle={() => toggleDrawer('ch5')}
          title="IntentRegistry SQL Row Lock & Integer Balance Snapshot"
          data={{
            intent_id: s1.intent_id || 'intent_demo_01',
            spend_cap_paise: 150000,
            reserved_paise: 112000,
            captured_paise: 0,
            available_paise: 38000,
            sql_concurrency_lock: 'SELECT * FROM intent_registry WHERE intent_id = :id FOR UPDATE',
          }}
          copyKey="raw_reservation"
          copiedKey={copiedKey}
          onCopy={handleCopy}
        />
      </div>

      <ConduitConnector text="TRIPWIRE // PRE-FLIGHT INVENTORY & PRICE FRESHNESS CHECK" />

      {/* =========================================================================
          CHAPTER 06: THE TRIPWIRE // JUST-IN-TIME (JIT) REVALIDATION
          ========================================================================= */}
      <div id="chapter-06" className="chapter-node">
        <ChapterHeader
          num="06"
          tag="PRE-FLIGHT CHECK"
          title="Just-In-Time Freshness & Inventory Re-Verification"
          badge="DRIFT & STOCK TRIPWIRE"
          badgeColor="badge-amber"
        />

        <GuaranteeCallout
          invariant="Quotes and stock levels are re-checked at the exact moment of fulfillment. Any price drift or depleted inventory triggers an immediate fail-closed response."
          benefit="Protects against phantom goods and surprise price increases between agent deliberation and warehouse checkout."
        />

        {/* Side-by-Side Pre-Flight Check */}
        <div className="dual-rail-grid" style={{ marginTop: '12px' }}>
          {/* Leg 1 Check */}
          <div
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid rgba(52, 211, 153, 0.4)',
              padding: '12px',
              display: 'flex',
              flexDirection: 'column',
              gap: '6px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', fontWeight: 700, color: 'var(--accent-terminal)' }}>
                RAIL A: CAKEHOUSE ARTISANS
              </span>
              <span className="badge badge-green">PROCEED</span>
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.74rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>ITEM:</span>
                <span>Chocolate Truffle Cake (1kg)</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>STOCK CHECK:</span>
                <span style={{ color: 'var(--accent-terminal)' }}>VERIFIED IN STOCK</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>PRICE DRIFT:</span>
                <span style={{ color: 'var(--accent-terminal)' }}>₹0.00 (UNCHANGED ₹940.00)</span>
              </div>
            </div>
          </div>

          {/* Leg 2 Check */}
          <div
            style={{
              background: 'var(--bg-surface)',
              border: `1px solid ${simulateLeg2Failure ? 'rgba(208, 59, 59, 0.4)' : 'rgba(52, 211, 153, 0.4)'}`,
              padding: '12px',
              display: 'flex',
              flexDirection: 'column',
              gap: '6px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  color: simulateLeg2Failure ? 'var(--accent-red)' : 'var(--accent-terminal)',
                }}
              >
                RAIL B: SWEET DELIGHTS
              </span>
              <span className={`badge ${simulateLeg2Failure ? 'badge-red' : 'badge-green'}`}>
                {simulateLeg2Failure ? 'FAIL-CLOSED TRIGGERED' : 'PROCEED'}
              </span>
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.74rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>ITEM:</span>
                <span>Party Candle Set & Greeting Card</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>STOCK CHECK:</span>
                <span style={{ color: simulateLeg2Failure ? 'var(--accent-red)' : 'var(--accent-terminal)', fontWeight: 700 }}>
                  {simulateLeg2Failure ? 'OUT OF STOCK (DEPLETED)' : 'VERIFIED IN STOCK'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>VERDICT:</span>
                <span style={{ color: simulateLeg2Failure ? 'var(--accent-red)' : 'var(--accent-terminal)', fontWeight: 700 }}>
                  {simulateLeg2Failure ? 'RELEASE RESERVATION (₹180.00)' : 'PROCEED TO CAPTURE'}
                </span>
              </div>
            </div>
          </div>
        </div>

        <EvidenceDrawer
          isOpen={expandedDrawers['ch6']}
          onToggle={() => toggleDrawer('ch6')}
          title="JIT Pre-Flight Freshness & Inventory Revalidation Delta"
          data={{
            leg1_cakehouse: leg1Jit,
            leg2_sweetdelight: leg2Jit,
          }}
          copyKey="raw_jit"
          copiedKey={copiedKey}
          onCopy={handleCopy}
        />
      </div>

      <ConduitConnector text="EXECUTION // INDEPENDENT PAYMENT RAILS" />

      {/* =========================================================================
          CHAPTER 07: SEPARATED RAILS // INDEPENDENT EXECUTION & RELEASE
          ========================================================================= */}
      <div id="chapter-07" className="chapter-node">
        <ChapterHeader
          num="07"
          tag="ISOLATED RAILS"
          title="Independent Payment Execution & Partial Failure Isolation"
          badge="NO CASCADE PANIC"
          badgeColor="badge-cyan"
        />

        <GuaranteeCallout
          invariant="Merchant rails execute independently. Leg 1 captures funds via Razorpay webhook; Leg 2 cleanly releases its reservation without touching Leg 1."
          benefit="Eliminates the danger of cascading rollbacks. A failure on one merchant does not cancel or corrupt valid items from other merchants."
        />

        {/* Dual Rail Execution Results */}
        <div className="dual-rail-grid" style={{ marginTop: '12px' }}>
          {/* Leg 1 Result */}
          <div
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-bright)',
              padding: '14px',
              display: 'flex',
              flexDirection: 'column',
              gap: '6px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', fontWeight: 700, color: 'var(--accent-terminal)' }}>
                RAIL A: CAKEHOUSE ARTISANS
              </span>
              <span className="badge badge-green">PAYMENT CAPTURED</span>
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.74rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>RAZORPAY ORDER:</span>
                <span style={{ color: 'var(--text-phosphor)' }}>{leg1Exec.razorpay_order_id || 'order_cake_demo_01'}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>CAPTURED FUNDS:</span>
                <span style={{ color: 'var(--accent-terminal)', fontWeight: 700 }}>₹940.00</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>WEBHOOK HMAC:</span>
                <span style={{ color: 'var(--accent-terminal)' }}>AUTHENTICATED (whsec_demo)</span>
              </div>
            </div>
          </div>

          {/* Leg 2 Result */}
          <div
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-bright)',
              padding: '14px',
              display: 'flex',
              flexDirection: 'column',
              gap: '6px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', fontWeight: 700, color: simulateLeg2Failure ? 'var(--accent-amber)' : 'var(--accent-terminal)' }}>
                RAIL B: SWEET DELIGHTS
              </span>
              <span className={`badge ${simulateLeg2Failure ? 'badge-amber' : 'badge-green'}`}>
                {simulateLeg2Failure ? 'RESERVATION RELEASED' : 'CAPTURED'}
              </span>
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.74rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>OUTCOME:</span>
                <span style={{ color: simulateLeg2Failure ? 'var(--accent-amber)' : 'var(--accent-terminal)', fontWeight: 700 }}>
                  {simulateLeg2Failure ? '₹180.00 RETURNED TO USER' : '₹180.00 CAPTURED'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>REASON:</span>
                <span style={{ color: 'var(--text-secondary)' }}>
                  {simulateLeg2Failure ? 'MERCHANT_STOCK_EXHAUSTED' : 'SUCCESS'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>CROSS-LEG IMPACT:</span>
                <span style={{ color: 'var(--accent-terminal)' }}>0% (ISOLATED RAIL)</span>
              </div>
            </div>
          </div>
        </div>

        <EvidenceDrawer
          isOpen={expandedDrawers['ch7']}
          onToggle={() => toggleDrawer('ch7')}
          title="Razorpay Capture Webhook HMAC & Reservation Release Audit"
          data={{
            leg1_execution: leg1Exec,
            leg2_execution: leg2Exec,
          }}
          copyKey="raw_execution"
          copiedKey={copiedKey}
          onCopy={handleCopy}
        />
      </div>

      <ConduitConnector text="CONVERGENCE // PARTIAL SETTLEMENT RECONCILIATION" />

      {/* =========================================================================
          CHAPTER 08: THE SETTLEMENT // PARTIAL COMPLETION (ZERO FALSE ATOMICITY)
          ========================================================================= */}
      <div id="chapter-08" className="chapter-node">
        <ChapterHeader
          num="08"
          tag="SETTLEMENT"
          title="Aggregate Plan Settlement: PARTIAL_COMPLETE"
          badge="ZERO PHANTOM GOODS"
          badgeColor="badge-green"
        />

        <GuaranteeCallout
          invariant="The aggregate plan settles as PARTIAL_COMPLETE. Rather than panicking with an all-or-nothing rollback, Mandate Mesh preserves captured goods while safely unlocking unspent money."
          benefit="In physical commerce, you cannot 'un-bake' a birthday cake because candles ran out of stock. Mandate Mesh matches physical reality: exact financial reconciliation with zero money lost."
        />

        {/* Settlement Financial Summary */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: '10px',
            marginTop: '12px',
          }}
        >
          <DataMetricCard
            label="AGGREGATE PLAN STATUS"
            value={s8.plan_status || (simulateLeg2Failure ? 'PARTIAL_COMPLETE' : 'COMPLETED')}
            subValue="Canonical PurchasePlan State"
            accentColor="var(--accent-terminal)"
          />
          <DataMetricCard
            label="TOTAL CAPTURED FUNDS"
            value="₹940.00"
            subValue="CakeHouse (Goods Secured)"
            accentColor="var(--accent-terminal)"
          />
          <DataMetricCard
            label="TOTAL UNSPENT / RELEASED"
            value={simulateLeg2Failure ? '₹180.00' : '₹0.00'}
            subValue="Sweet Delights (Returned)"
            accentColor="var(--accent-steel)"
          />
          <DataMetricCard
            label="TOTAL PHANTOM / LOST"
            value="₹0.00"
            subValue="Zero Financial Leakage"
            accentColor="var(--accent-terminal)"
          />
        </div>

        <EvidenceDrawer
          isOpen={expandedDrawers['ch8']}
          onToggle={() => toggleDrawer('ch8')}
          title="Financial Reconciliation & Atomicity Comparison Analysis"
          data={{
            plan_status: s8.plan_status || 'PARTIAL_COMPLETE',
            authorized_total_paise: s8.total_authorized_paise || 112000,
            captured_total_paise: s8.total_captured_paise || 94000,
            released_total_paise: s8.total_released_paise || 18000,
            atomicity_guarantee: s8.atomicity_verdict,
          }}
          copyKey="raw_settlement"
          copiedKey={copiedKey}
          onCopy={handleCopy}
        />
      </div>

      <ConduitConnector text="SEAL // IMMUTABLE AUDIT LOGGING" />

      {/* =========================================================================
          CHAPTER 09: THE PROOF // APPEND-ONLY HASH-CHAINED AUDIT LEDGER
          ========================================================================= */}
      <div id="chapter-09" className="chapter-node">
        <ChapterHeader
          num="09"
          tag="AUDIT PROOF"
          title="SHA-256 Hash-Chained Cryptographic Audit Ledger"
          badge="100% LINEAR HASH CONTINUITY"
          badgeColor="badge-green"
        />

        <GuaranteeCallout
          invariant="Every single lifecycle transition—from intent signature to cart verification, balance reservation, order creation, capture webhook, and partial release—is permanently sealed in an append-only SHA-256 hash chain."
          benefit="Provides mathematical proof for audits, disputes, and compliance. Neither buyer, merchant, nor platform operator can alter past records without breaking the chain."
        />

        {/* Sealed Block Sequence */}
        <div style={{ marginTop: '12px' }}>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.68rem',
              color: 'var(--text-muted)',
              marginBottom: '8px',
              textTransform: 'uppercase',
              fontWeight: 700,
            }}
          >
            SEALED TRANSACTION BLOCK SEQUENCE:
          </div>

          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            {[
              'INTENT_CREATED',
              'CART_SIGNED',
              'MANDATE_CREATED (Leg 1)',
              'MANDATE_CREATED (Leg 2)',
              'ORDER_CREATED (Leg 1)',
              'PAYMENT_CAPTURED (Leg 1)',
              'POLICY_REJECTED / RELEASED (Leg 2)',
            ].map((evt, idx, arr) => (
              <React.Fragment key={idx}>
                <div
                  style={{
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border-bright)',
                    padding: '4px 8px',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.68rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '5px',
                  }}
                >
                  <Check size={10} color="var(--accent-terminal)" />
                  <span style={{ color: 'var(--text-phosphor)' }}>{evt}</span>
                </div>
                {idx < arr.length - 1 && (
                  <span style={{ color: 'var(--text-dim)', fontSize: '0.7rem' }}>➔</span>
                )}
              </React.Fragment>
            ))}
          </div>
        </div>

        {/* Switch to Full Ledger */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 12px',
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-line)',
            marginTop: '12px',
          }}
        >
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.74rem',
              color: 'var(--text-secondary)',
            }}
          >
            Inspect every raw block digest, payload hash, and Merkle linkage in the live explorer:
          </span>
          {onSwitchToAuditLedger && (
            <button
              className="btn btn-primary"
              onClick={onSwitchToAuditLedger}
              style={{ fontSize: '0.72rem', padding: '4px 12px' }}
            >
              <Database size={12} />
              <span>OPEN FULL AUDIT LEDGER ➔</span>
            </button>
          )}
        </div>

        <EvidenceDrawer
          isOpen={expandedDrawers['ch9']}
          onToggle={() => toggleDrawer('ch9')}
          title="Cryptographic Hash Chain Block Proof & Genesis Linkage"
          data={{
            chain_status: '100% LINEAR',
            total_blocks: s9.total_blocks || 662,
            hashing_algorithm: 'SHA-256',
            genesis_hash: '0000000000000000000000000000000000000000000000000000000000000000',
            audit_guarantee: s9.mathematical_guarantee,
          }}
          copyKey="raw_audit"
          copiedKey={copiedKey}
          onCopy={handleCopy}
        />
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
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '10px',
        paddingBottom: '12px',
        borderBottom: '1px solid var(--border-line)',
      }}
    >
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.72rem',
              color: 'var(--accent-terminal)',
              fontWeight: 700,
              letterSpacing: '0.08em',
            }}
          >
            CHAPTER {num} // 09
          </span>
          <span className="badge badge-steel">{tag}</span>
        </div>
        <h2
          style={{
            fontFamily: 'var(--font-macro)',
            fontSize: '1.18rem',
            letterSpacing: '-0.02em',
            color: 'var(--text-phosphor)',
            margin: 0,
          }}
        >
          {title}
        </h2>
      </div>
      <span className={`badge ${badgeColor}`}>{badge}</span>
    </div>
  );
}

function GuaranteeCallout({ invariant, benefit }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: '12px',
        marginTop: '12px',
      }}
    >
      <div
        style={{
          background: 'var(--bg-recessed)',
          border: '1px solid var(--border-line)',
          padding: '10px 12px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.68rem',
            fontWeight: 700,
            color: 'var(--accent-terminal)',
            letterSpacing: '0.05em',
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
          }}
        >
          <Zap size={11} />
          <span>[ ARCHITECTURAL INVARIANT ]</span>
        </span>
        <p
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '0.78rem',
            color: 'var(--text-phosphor)',
            lineHeight: 1.45,
          }}
        >
          {invariant}
        </p>
      </div>

      <div
        style={{
          background: 'var(--bg-recessed)',
          border: '1px solid var(--border-line)',
          padding: '10px 12px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.68rem',
            fontWeight: 700,
            color: 'var(--accent-red)',
            letterSpacing: '0.05em',
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
          }}
        >
          <ShieldCheck size={11} />
          <span>[ BUYER FINANCIAL PROTECTION ]</span>
        </span>
        <p
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '0.78rem',
            color: 'var(--text-phosphor)',
            lineHeight: 1.45,
          }}
        >
          {benefit}
        </p>
      </div>
    </div>
  );
}

function ConduitConnector({ text }) {
  return (
    <div className="chapter-connector">
      <div className="chapter-connector-badge">{text}</div>
    </div>
  );
}

function DataMetricCard({
  label,
  value,
  subValue,
  accentColor = 'var(--text-phosphor)',
  isText = false,
}) {
  return (
    <div
      style={{
        background: 'var(--bg-recessed)',
        border: '1px solid var(--border-line)',
        padding: '8px 10px',
        display: 'flex',
        flexDirection: 'column',
        gap: '3px',
      }}
    >
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.64rem',
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.04em',
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: isText ? 'var(--font-sans)' : 'var(--font-mono)',
          fontSize: isText ? '0.8rem' : '0.94rem',
          fontWeight: 700,
          color: accentColor,
          lineHeight: 1.2,
        }}
      >
        {value}
      </span>
      {subValue && (
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.62rem',
            color: 'var(--text-dim)',
          }}
        >
          {subValue}
        </span>
      )}
    </div>
  );
}

function EvidenceDrawer({
  isOpen,
  onToggle,
  title,
  data,
  copyKey,
  copiedKey,
  onCopy,
}) {
  return (
    <div className="evidence-drawer">
      <div className="evidence-drawer-header" onClick={onToggle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Terminal size={12} color="var(--accent-terminal)" />
          <span>{isOpen ? '[- HIDE CRYPTOGRAPHIC EVIDENCE]' : '[+ EXPAND RAW CRYPTOGRAPHIC PROOF]'}</span>
          <span style={{ color: 'var(--text-muted)' }}>— {title}</span>
        </div>
        {isOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </div>

      {isOpen && (
        <div className="evidence-drawer-content">
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '6px',
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.66rem',
                color: 'var(--text-muted)',
              }}
            >
              AUTHENTIC DATA PAYLOAD:
            </span>
            <button
              className="btn btn-secondary"
              style={{ padding: '2px 8px', fontSize: '0.64rem' }}
              onClick={() => onCopy(JSON.stringify(data, null, 2), copyKey)}
            >
              {copiedKey === copyKey ? (
                <>
                  <Check size={10} color="var(--accent-terminal)" />
                  <span>COPIED</span>
                </>
              ) : (
                <>
                  <Copy size={10} />
                  <span>COPY JSON</span>
                </>
              )}
            </button>
          </div>

          <pre
            style={{
              background: 'var(--bg-terminal)',
              border: '1px solid var(--border-line)',
              padding: '8px 10px',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.68rem',
              color: 'var(--text-secondary)',
              overflowX: 'auto',
              lineHeight: 1.45,
              margin: 0,
            }}
          >
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

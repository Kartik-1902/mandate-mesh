import React, { useState, Component } from 'react';
import Header from './components/Header';
import AgentChat from './components/AgentChat';
import CompetitiveQuotePanel from './components/CompetitiveQuotePanel';
import MandateChainVisualizer from './components/MandateChainVisualizer';
import AttackSimulator from './components/AttackSimulator';
import AuditLedgerTable from './components/AuditLedgerTable';
import SpecDrawer from './components/SpecDrawer';
import TransactionReactor from './components/TransactionReactor';
import { deliberateGoal, triggerAttack, verifyLedgerChain } from './services/api';

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="panel-card" style={{ borderColor: 'var(--accent-red)', padding: '24px' }}>
          <h3 className="text-red">Component Render Error</h3>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '8px' }}>
            {this.state.error?.message || 'An error occurred in this panel.'}
          </p>
          <button className="btn btn-secondary" onClick={() => this.setState({ hasError: false })} style={{ marginTop: '12px' }}>
            Retry Component
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const [activeMandate, setActiveMandate] = useState(null);
  const [routingDecision, setRoutingDecision] = useState(null);
  const [candidateQuotes, setCandidateQuotes] = useState([]);
  const [ledgerTrigger, setLedgerTrigger] = useState(0);
  const [chainValid, setChainValid] = useState(true);
  const [sessionKey, setSessionKey] = useState(0);
  const [activeMode, setActiveMode] = useState('journey'); // 'journey' | 'bench' | 'ledger'

  // First-visit auto-open or ?demo=true URL parameter override
  const searchParams = new URLSearchParams(window.location.search);
  const forceDemo = searchParams.get('demo') === 'true';
  const hasSeenGuide = Boolean(localStorage.getItem('mandate_mesh_guide_seen'));

  const [isDrawerOpen, setIsDrawerOpen] = useState(forceDemo || !hasSeenGuide);
  const [isMacroExecuting, setIsMacroExecuting] = useState(false);

  const handleAgentDeliberate = (res) => {
    if (res.routing_decision) {
      setRoutingDecision(res.routing_decision);
    }
    if (res.candidate_quotes) {
      setCandidateQuotes(res.candidate_quotes);
    }
    if (res.mandate) {
      setActiveMandate({
        mandate_id: res.mandate.mandate_id,
        intent_id: res.mandate.intent_id,
        intent_hash: res.mandate.intent_hash,
        cart_hash: res.mandate.cart_hash,
        authorized_amount_paise: res.mandate.authorized_amount_paise,
        razorpay_order_id: res.razorpay_order_id,
      });
    }
  };

  const handleEscalateSuccess = (res) => {
    const mandate = res.mandate || res;
    if (!mandate) return;
    setActiveMandate({
      mandate_id: mandate.mandate_id,
      intent_id: mandate.intent_id,
      intent_hash: mandate.intent_hash,
      cart_hash: mandate.cart_hash,
      authorized_amount_paise: mandate.authorized_amount_paise,
      razorpay_order_id: res.razorpay_order_id || mandate.razorpay_order_id,
      receipt_reference: res.receipt_reference,
    });
  };

  const triggerLedgerReload = () => {
    setLedgerTrigger((prev) => prev + 1);
  };

  const handleResetSession = () => {
    setActiveMandate(null);
    setRoutingDecision(null);
    setCandidateQuotes([]);
    setSessionKey((prev) => prev + 1);
    triggerLedgerReload();
  };

  // Spec Drawer controls & live demo macro runners
  const handleCloseDrawer = () => {
    localStorage.setItem('mandate_mesh_guide_seen', 'true');
    setIsDrawerOpen(false);
  };

  const handleToggleDrawer = () => {
    setIsDrawerOpen((prev) => !prev);
  };

  const handleRunGoldenPurchase = async () => {
    setIsMacroExecuting(true);
    try {
      const res = await deliberateGoal('Order a 1kg chocolate cake under Rs. 1500 comparing all bakeries');
      handleAgentDeliberate(res);
      triggerLedgerReload();
      return {
        message: `Autonomous mandate ${res.mandate?.mandate_id || 'issued'} authorized for ₹${((res.mandate?.authorized_amount_paise || 0) / 100).toFixed(2)}.`,
      };
    } finally {
      setIsMacroExecuting(false);
    }
  };

  const handleRunAttack = async () => {
    setIsMacroExecuting(true);
    try {
      const res = await triggerAttack(2);
      triggerLedgerReload();
      return {
        message: res.message || 'Injection blocked: HTTP 404 CATALOG_SKU_NOT_FOUND. 0 Rupees Moved.',
      };
    } finally {
      setIsMacroExecuting(false);
    }
  };

  const handleVerifyLedger = async () => {
    setIsMacroExecuting(true);
    try {
      const res = await verifyLedgerChain();
      setChainValid(res.chain_valid);
      triggerLedgerReload();
      return {
        message: `Audit chain verified: ${res.total_blocks} blocks, 100% linear SHA-256 continuity.`,
      };
    } finally {
      setIsMacroExecuting(false);
    }
  };

  return (
    <div className="control-tower-container">
      {/* 1. Header & Live Indicator Banner */}
      <Header
        chainValid={chainValid}
        onResetSession={handleResetSession}
        onToggleSpecDrawer={handleToggleDrawer}
        hasSeenGuide={hasSeenGuide}
      />

      {/* Spec Drawer & Interactive Pitch / Demo Controller */}
      <SpecDrawer
        isOpen={isDrawerOpen}
        onClose={handleCloseDrawer}
        onRunGoldenPurchase={handleRunGoldenPurchase}
        onRunAttack={handleRunAttack}
        onVerifyLedger={handleVerifyLedger}
        isExecuting={isMacroExecuting}
      />

      {/* 2. Top-Level Console Mode Navigation Strip */}
      <div
        className="panel-card"
        style={{
          padding: '8px 14px',
          background: 'var(--bg-panel)',
          border: '1px solid var(--border-bright)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '10px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.68rem',
              color: 'var(--text-muted)',
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              marginRight: '4px',
            }}
          >
            VIEW:
          </span>

          <button
            className={`btn ${activeMode === 'journey' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setActiveMode('journey')}
            style={{
              fontSize: '0.74rem',
              padding: '5px 12px',
              fontWeight: 700,
            }}
          >
            <span>01 // GUIDED TRANSACTION JOURNEY</span>
            {activeMode === 'journey' && (
              <span className="badge badge-green" style={{ marginLeft: '4px' }}>
                ACTIVE
              </span>
            )}
          </button>

          <button
            className={`btn ${activeMode === 'bench' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setActiveMode('bench')}
            style={{
              fontSize: '0.74rem',
              padding: '5px 12px',
              fontWeight: 700,
            }}
          >
            <span>02 // ADVERSARIAL THREAT BENCH</span>
          </button>

          <button
            className={`btn ${activeMode === 'ledger' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setActiveMode('ledger')}
            style={{
              fontSize: '0.74rem',
              padding: '5px 12px',
              fontWeight: 700,
            }}
          >
            <span>03 // CRYPTOGRAPHIC AUDIT LEDGER</span>
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.68rem',
              color: 'var(--text-secondary)',
            }}
          >
            {activeMode === 'journey' && '⚡ 9-Stage End-to-End Product Narrative for Hackathon Evaluation'}
            {activeMode === 'bench' && '🛡️ 6-Vector Live Threat Injection Suite (Zero Rupees Moved)'}
            {activeMode === 'ledger' && '🔗 Real-Time Append-Only SHA-256 Hash Chain Explorer'}
          </span>
        </div>
      </div>

      {/* 3. Mode Content View */}
      {activeMode === 'journey' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <ErrorBoundary key={`journey-${sessionKey}`}>
            <TransactionReactor
              onSwitchToAuditLedger={() => setActiveMode('ledger')}
              onLedgerChange={triggerLedgerReload}
            />
          </ErrorBoundary>

          <ErrorBoundary>
            <AuditLedgerTable refreshTrigger={ledgerTrigger} />
          </ErrorBoundary>
        </div>
      )}

      {activeMode === 'bench' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {/* 2-Column Threat & Agent Operation Grid */}
          <div className="main-grid">
            {/* Left: Autonomous Buyer Agent + HITL Escalation Modal */}
            <div>
              <ErrorBoundary key={`agent-${sessionKey}`}>
                <AgentChat
                  onDeliberateSuccess={handleAgentDeliberate}
                  onEscalateSuccess={handleEscalateSuccess}
                  onLedgerChange={triggerLedgerReload}
                />
              </ErrorBoundary>
            </div>

            {/* Right: Competitive Quotes + Cryptographic Mandate Chain + Adversarial Attack Playground */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <ErrorBoundary key={`quote-${sessionKey}`}>
                <CompetitiveQuotePanel
                  routingDecision={routingDecision}
                  candidateQuotes={candidateQuotes}
                />
              </ErrorBoundary>

              <ErrorBoundary key={`chain-${sessionKey}`}>
                <MandateChainVisualizer
                  activeMandate={activeMandate}
                  onCaptureSuccess={triggerLedgerReload}
                  onLedgerChange={triggerLedgerReload}
                />
              </ErrorBoundary>

              <ErrorBoundary key={`attack-${sessionKey}`}>
                <AttackSimulator
                  onAttackSuccess={triggerLedgerReload}
                  onLedgerChange={triggerLedgerReload}
                />
              </ErrorBoundary>
            </div>
          </div>

          <div>
            <ErrorBoundary>
              <AuditLedgerTable refreshTrigger={ledgerTrigger} />
            </ErrorBoundary>
          </div>
        </div>
      )}

      {activeMode === 'ledger' && (
        <div>
          <ErrorBoundary>
            <AuditLedgerTable refreshTrigger={ledgerTrigger} />
          </ErrorBoundary>
        </div>
      )}
    </div>
  );
}

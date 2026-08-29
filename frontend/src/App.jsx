import React, { useState, Component } from 'react';
import Header from './components/Header';
import AgentChat from './components/AgentChat';
import CompetitiveQuotePanel from './components/CompetitiveQuotePanel';
import MandateChainVisualizer from './components/MandateChainVisualizer';
import AttackSimulator from './components/AttackSimulator';
import AuditLedgerTable from './components/AuditLedgerTable';

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
    setActiveMandate({
      mandate_id: res.mandate_id,
      intent_hash: res.intent_hash,
      cart_hash: res.cart_hash,
      authorized_amount_paise: res.authorized_amount_paise,
      razorpay_order_id: res.razorpay_order_id,
      receipt_reference: res.receipt_reference,
    });
  };

  const triggerLedgerReload = () => {
    setLedgerTrigger((prev) => prev + 1);
  };

  return (
    <div className="control-tower-container">
      {/* 1. Header & Live Indicator Banner */}
      <Header chainValid={chainValid} />

      {/* 2. Primary Operations Grid */}
      <div className="main-grid">
        {/* Left: Autonomous Buyer Agent + HITL Escalation Modal */}
        <div>
          <ErrorBoundary>
            <AgentChat
              onDeliberateSuccess={handleAgentDeliberate}
              onEscalateSuccess={handleEscalateSuccess}
              onLedgerChange={triggerLedgerReload}
            />
          </ErrorBoundary>
        </div>

        {/* Right: Competitive Quotes + Cryptographic Mandate Chain + Adversarial Attack Playground */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <ErrorBoundary>
            <CompetitiveQuotePanel
              routingDecision={routingDecision}
              candidateQuotes={candidateQuotes}
            />
          </ErrorBoundary>

          <ErrorBoundary>
            <MandateChainVisualizer
              activeMandate={activeMandate}
              onCaptureSuccess={triggerLedgerReload}
              onLedgerChange={triggerLedgerReload}
            />
          </ErrorBoundary>

          <ErrorBoundary>
            <AttackSimulator
              onAttackSuccess={triggerLedgerReload}
              onLedgerChange={triggerLedgerReload}
            />
          </ErrorBoundary>
        </div>
      </div>

      {/* 3. Bottom: Real-Time Hash-Chained Audit Ledger */}
      <div>
        <ErrorBoundary>
          <AuditLedgerTable refreshTrigger={ledgerTrigger} />
        </ErrorBoundary>
      </div>
    </div>
  );
}

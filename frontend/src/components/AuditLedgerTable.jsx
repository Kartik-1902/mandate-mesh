import React, { useState, useEffect } from 'react';
import { Database, RefreshCw, ShieldCheck, CheckCircle2, ShieldAlert } from 'lucide-react';
import { getLedgerEntries, verifyLedgerChain } from '../services/api';

export default function AuditLedgerTable({ refreshTrigger }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [verifyStatus, setVerifyStatus] = useState(null);
  const [verifying, setVerifying] = useState(false);

  const fetchEntries = async () => {
    setLoading(true);
    try {
      const data = await getLedgerEntries(15);
      if (Array.isArray(data)) {
        setEntries(data);
      } else if (data && Array.isArray(data.entries)) {
        setEntries(data.entries);
      } else {
        setEntries([]);
      }
    } catch (err) {
      console.error('Failed to load ledger entries:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async () => {
    setVerifying(true);
    try {
      const res = await verifyLedgerChain();
      setVerifyStatus(res);
    } catch (err) {
      console.error('Ledger verification failed:', err);
    } finally {
      setVerifying(false);
    }
  };

  useEffect(() => {
    fetchEntries();
    handleVerify();
  }, [refreshTrigger]);

  const getEntryBadgeClass = (type) => {
    switch (type) {
      case 'INTENT_ISSUED': return 'badge-cyan';
      case 'CART_SIGNED': return 'badge-purple';
      case 'MANDATE_CREATED': return 'badge-green';
      case 'POLICY_REJECTED': return 'badge-red';
      case 'ORDER_CREATED': return 'badge-amber';
      case 'PAYMENT_CAPTURED':
      case 'RECEIPT_ISSUED': return 'badge-green';
      default: return 'badge-cyan';
    }
  };

  return (
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      
      {/* Header */}
      <div className="panel-card-header">
        <div className="panel-title">
          <Database size={20} className="text-cyan" />
          <span>Append-Only Hash-Chained Audit Ledger</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {verifyStatus && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', fontWeight: 600, color: verifyStatus.valid ? 'var(--accent-green)' : 'var(--accent-red)' }}>
              {verifyStatus.valid ? <CheckCircle2 size={16} /> : <ShieldAlert size={16} />}
              <span>{verifyStatus.valid ? `Chain Verified (${verifyStatus.total_entries || 0} entries)` : 'Broken Chain'}</span>
            </div>
          )}

          <button
            className="btn btn-secondary"
            onClick={handleVerify}
            disabled={verifying}
            style={{ padding: '4px 10px', fontSize: '0.75rem' }}
          >
            <ShieldCheck size={14} />
            {verifying ? 'Verifying...' : 'Verify Cryptographic Chain'}
          </button>

          <button
            className="btn btn-secondary"
            onClick={fetchEntries}
            disabled={loading}
            style={{ padding: '4px 10px', fontSize: '0.75rem' }}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* Table Container */}
      <div style={{ overflowX: 'auto', maxHeight: '340px' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
              <th style={{ padding: '8px 12px' }}>ID</th>
              <th style={{ padding: '8px 12px' }}>Entry Type</th>
              <th style={{ padding: '8px 12px' }}>Actor</th>
              <th style={{ padding: '8px 12px' }}>Payload Hash</th>
              <th style={{ padding: '8px 12px' }}>Prev Hash</th>
              <th style={{ padding: '8px 12px' }}>Entry Hash (Chained)</th>
              <th style={{ padding: '8px 12px' }}>Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr
                key={entry.id}
                style={{
                  borderBottom: '1px solid rgba(255,255,255,0.03)',
                  transition: 'background 0.2s ease',
                }}
                onMouseOver={(e) => (e.currentTarget.style.background = 'var(--bg-surface)')}
                onMouseOut={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                <td className="font-mono" style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>
                  #{entry.id}
                </td>
                <td style={{ padding: '8px 12px' }}>
                  <span className={`badge ${getEntryBadgeClass(entry.entry_type)}`} style={{ fontSize: '0.68rem' }}>
                    {entry.entry_type}
                  </span>
                </td>
                <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>
                  {entry.actor}
                </td>
                <td className="font-mono text-cyan" style={{ padding: '8px 12px', fontSize: '0.72rem' }}>
                  {entry.payload_hash.slice(0, 10)}...
                </td>
                <td className="font-mono text-muted" style={{ padding: '8px 12px', fontSize: '0.72rem' }}>
                  {entry.prev_hash.slice(0, 10)}...
                </td>
                <td className="font-mono text-green" style={{ padding: '8px 12px', fontSize: '0.72rem' }}>
                  {entry.entry_hash.slice(0, 10)}...
                </td>
                <td style={{ padding: '8px 12px', color: 'var(--text-muted)', fontSize: '0.72rem' }}>
                  {new Date(entry.created_at).toLocaleTimeString()}
                </td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr>
                <td colSpan="7" style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
                  No audit ledger entries recorded yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

    </div>
  );
}

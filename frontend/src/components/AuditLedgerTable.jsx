import React, { useState, useEffect } from 'react';
import { Database, RefreshCw, ShieldCheck, CheckCircle2, ShieldAlert, Terminal } from 'lucide-react';
import { getLedgerEntries, verifyLedgerChain } from '../services/api';

export default function AuditLedgerTable({ refreshTrigger }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [verifyStatus, setVerifyStatus] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const [expandedPayloadIndex, setExpandedPayloadIndex] = useState(null);

  const fetchEntries = async () => {
    setLoading(true);
    try {
      const data = await getLedgerEntries(20);
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

  const getEntryBadge = (type) => {
    switch (type) {
      case 'INTENT_ISSUED':
        return <span className="badge badge-steel">[INTENT]</span>;
      case 'CART_SIGNED':
        return <span className="badge badge-steel">[CART_SIG]</span>;
      case 'MANDATE_CREATED':
        return <span className="badge badge-green">[MANDATE_ACTIVE]</span>;
      case 'POLICY_REJECTED':
        return <span className="badge badge-red">[POLICY_REJECT]</span>;
      case 'ORDER_CREATED':
        return <span className="badge badge-amber">[ORDER_CREATED]</span>;
      case 'WEBHOOK_RECEIVED':
        return <span className="badge badge-steel">[WEBHOOK]</span>;
      case 'PAYMENT_CAPTURED':
      case 'RECEIPT_ISSUED':
        return <span className="badge badge-green">[CAPTURED_PROOF]</span>;
      default:
        return <span className="badge badge-steel">[{type || 'LOG'}]</span>;
    }
  };

  const formatIST = (dateStr) => {
    if (!dateStr) return '—';
    const normalizedStr = dateStr.endsWith('Z') || dateStr.includes('+') ? dateStr : `${dateStr}Z`;
    const date = new Date(normalizedStr);
    if (isNaN(date.getTime())) return dateStr;
    return date.toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    }) + ' IST';
  };

  return (
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      
      {/* Header */}
      <div className="panel-card-header" style={{ marginBottom: 0 }}>
        <div className="panel-title">
          <Database size={16} color="var(--text-phosphor)" />
          <span>APPEND-ONLY HASH-CHAINED AUDIT LEDGER // MAINFRAME LOG</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {verifyStatus && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.72rem',
              fontWeight: 700,
              color: verifyStatus.valid ? 'var(--accent-terminal)' : 'var(--accent-red)',
              background: 'var(--bg-recessed)',
              padding: '4px 8px',
              border: `1px solid ${verifyStatus.valid ? 'var(--accent-terminal)' : 'var(--accent-red)'}`,
            }}>
              {verifyStatus.valid ? <CheckCircle2 size={13} /> : <ShieldAlert size={13} />}
              <span>{verifyStatus.valid ? `CHAIN INTEGRITY: 100% LINEAR (${verifyStatus.total_entries || 0} BLOCKS)` : 'INTEGRITY ALERT: BROKEN CHAIN'}</span>
            </div>
          )}

          <button
            className="btn btn-secondary"
            onClick={handleVerify}
            disabled={verifying}
            style={{ padding: '4px 8px', fontSize: '0.7rem' }}
          >
            <ShieldCheck size={13} />
            {verifying ? 'AUDITING...' : '[ AUDIT CHAIN ]'}
          </button>

          <button
            className="btn btn-secondary"
            onClick={fetchEntries}
            disabled={loading}
            style={{ padding: '4px 8px', fontSize: '0.7rem' }}
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            [ RELOAD ]
          </button>
        </div>
      </div>

      {/* Mainframe Tabular Ledger View */}
      <div style={{ overflowX: 'auto', border: '1px solid var(--border-line)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontFamily: 'var(--font-mono)', fontSize: '0.72rem' }}>
          <thead>
            <tr style={{ background: 'var(--bg-recessed)', borderBottom: '1px solid var(--border-bright)', color: 'var(--text-muted)' }}>
              <th style={{ padding: '8px 10px', width: '60px' }}>BLK #</th>
              <th style={{ padding: '8px 10px', width: '160px' }}>TIMESTAMP (IST)</th>
              <th style={{ padding: '8px 10px', width: '140px' }}>EVENT TYPE</th>
              <th style={{ padding: '8px 10px', width: '130px' }}>ACTOR</th>
              <th style={{ padding: '8px 10px' }}>SHA-256 BLOCK HASH</th>
              <th style={{ padding: '8px 10px' }}>PREV HASH LINK</th>
              <th style={{ padding: '8px 10px', width: '80px', textAlign: 'center' }}>PAYLOAD</th>
            </tr>
          </thead>
          <tbody>
            {entries.length > 0 ? (
              entries.map((entry, idx) => {
                const blockSeq = entry.sequence_number || entry.id || idx + 1;
                const timestampVal = entry.created_at || entry.timestamp;
                const eventTypeVal = entry.entry_type || entry.event_type;
                const actorVal = entry.actor || entry.actor_id || 'system:core';
                const currentHashVal = entry.entry_hash || entry.current_hash;
                const prevHashVal = entry.prev_hash || entry.previous_hash;

                return (
                  <React.Fragment key={entry.id || idx}>
                    <tr
                      style={{
                        borderBottom: '1px solid var(--border-line)',
                        background: idx % 2 === 0 ? 'var(--bg-panel)' : 'var(--bg-recessed)',
                      }}
                    >
                      <td style={{ padding: '8px 10px', color: 'var(--text-muted)', fontWeight: 700 }}>
                        #{String(blockSeq).padStart(4, '0')}
                      </td>
                      <td style={{ padding: '8px 10px', color: 'var(--text-secondary)' }}>
                        {formatIST(timestampVal)}
                      </td>
                      <td style={{ padding: '8px 10px' }}>
                        {getEntryBadge(eventTypeVal)}
                      </td>
                      <td style={{ padding: '8px 10px', color: 'var(--text-phosphor)' }}>
                        {actorVal}
                      </td>
                      <td style={{ padding: '8px 10px', color: 'var(--accent-steel)' }} title={currentHashVal || ''}>
                        {currentHashVal ? `${currentHashVal.substring(0, 16)}...` : '—'}
                      </td>
                      <td style={{ padding: '8px 10px', color: 'var(--text-muted)' }} title={prevHashVal || ''}>
                        {prevHashVal ? `${prevHashVal.substring(0, 16)}...` : '0000000000000000...'}
                      </td>
                      <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                        <button
                          className="btn btn-secondary"
                          onClick={() => setExpandedPayloadIndex(expandedPayloadIndex === idx ? null : idx)}
                          style={{ padding: '2px 6px', fontSize: '0.62rem' }}
                        >
                          {expandedPayloadIndex === idx ? '[ HIDE ]' : '[ VIEW ]'}
                        </button>
                      </td>
                    </tr>

                  {expandedPayloadIndex === idx && (
                    <tr style={{ background: 'var(--bg-terminal)', borderBottom: '1px solid var(--border-bright)' }}>
                      <td colSpan="7" style={{ padding: '10px 14px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                            RAW BLOCK RECORD TELEMETRY // FULL SIGNED PAYLOAD:
                          </span>
                          <pre style={{
                            margin: 0,
                            padding: '8px 10px',
                            background: 'var(--bg-recessed)',
                            border: '1px solid var(--border-line)',
                            color: 'var(--text-phosphor)',
                            fontSize: '0.7rem',
                            maxHeight: '160px',
                            overflowY: 'auto',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-all',
                          }}>
                            {JSON.stringify(entry.payload || entry, null, 2)}
                          </pre>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })
          ) : (
              <tr>
                <td colSpan="7" style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
                  NO LEDGER BLOCKS DISCOVERED. DELIBERATE AN INTENT TO GENERATE IMMUTABLE AUDIT RECORDS.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

    </div>
  );
}

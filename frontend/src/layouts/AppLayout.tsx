import { Link, NavLink, Outlet, useParams } from 'react-router-dom';
import { useTheme } from '../theme';
import {
  LayoutDashboard, FolderKanban, Eye, ShieldCheck,
  Plus, Sun, Moon, ArrowRightLeft, Radio
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api';

export default function AppLayout() {
  const { theme, toggle } = useTheme();
  const { jobId } = useParams();
  const [backendStatus, setBackendStatus] = useState<'checking' | 'online' | 'offline'>('checking');

  useEffect(() => {
    api.getStatus()
      .then(() => setBackendStatus('online'))
      .catch(() => setBackendStatus('offline'));
  }, []);

  return (
    <div className="app-layout">
      {/* ── Sidebar ─────────────────────────────────────── */}
      <aside className="app-sidebar">
        <Link to="/" style={{ textDecoration: 'none' }}>
          <div className="sidebar-logo">
            <div className="sidebar-logo-icon">M</div>
            <div>
              <div className="sidebar-logo-text">MSTR → Tableau</div>
              <div style={{ fontSize: 10, color: 'var(--ink-3)', fontWeight: 500 }}>Migration Platform</div>
            </div>
            <span className="sidebar-logo-badge">v0.1</span>
          </div>
        </Link>

        {/* Backend health status badge */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 10px',
          background: 'var(--field)',
          borderRadius: 'var(--radius-full)',
          fontSize: 11,
          fontWeight: 500,
          color: 'var(--ink-2)',
          marginBottom: 16
        }}>
          <span style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            backgroundColor: backendStatus === 'online' ? 'var(--green)' : backendStatus === 'offline' ? 'var(--red)' : 'var(--yellow)',
            display: 'inline-block',
            boxShadow: backendStatus === 'online' ? '0 0 6px var(--green)' : undefined
          }} />
          <span>API Engine: {backendStatus === 'online' ? 'Operational' : backendStatus === 'offline' ? 'Connecting...' : 'Checking'}</span>
        </div>

        <p className="sidebar-section-label">Navigation</p>
        <nav className="sidebar-nav">
          <NavLink to="/" end className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`}>
            <LayoutDashboard size={16} className="icon" />
            Dashboard
          </NavLink>

          <NavLink to="/jobs/new" className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`}>
            <Plus size={16} className="icon" />
            New Job
          </NavLink>
        </nav>

        {jobId && (
          <>
            <p className="sidebar-section-label">Current Job</p>
            <nav className="sidebar-nav">
              <NavLink to={`/jobs/${jobId}`} end className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`}>
                <FolderKanban size={16} className="icon" />
                Overview
              </NavLink>
              <NavLink to={`/jobs/${jobId}/objects`} className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`}>
                <ArrowRightLeft size={16} className="icon" />
                Objects
              </NavLink>
              <NavLink to={`/jobs/${jobId}/review`} className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`}>
                <Eye size={16} className="icon" />
                Review Queue
              </NavLink>
              <NavLink to={`/jobs/${jobId}/validation`} className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`}>
                <ShieldCheck size={16} className="icon" />
                Validation
              </NavLink>
            </nav>
          </>
        )}

        {/* Bottom section */}
        <div style={{ marginTop: 'auto', paddingTop: 20 }}>
          <div className="sidebar-section-label">Appearance</div>
          <div className="theme-toggle" style={{ marginTop: 8, marginLeft: 8 }}>
            <div className={`theme-toggle-indicator ${theme === 'dark' ? 'dark' : ''}`} />
            <button
              className={`theme-toggle-btn ${theme === 'light' ? 'active' : ''}`}
              onClick={() => theme === 'dark' && toggle()}
              aria-label="Light mode"
            >
              <Sun size={13} />
            </button>
            <button
              className={`theme-toggle-btn ${theme === 'dark' ? 'active' : ''}`}
              onClick={() => theme === 'light' && toggle()}
              aria-label="Dark mode"
            >
              <Moon size={13} />
            </button>
          </div>
        </div>
      </aside>

      {/* ── Main content ────────────────────────────────── */}
      <main className="app-main">
        <div className="app-content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

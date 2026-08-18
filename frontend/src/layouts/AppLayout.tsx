import { NavLink, Outlet, useParams } from 'react-router-dom';
import { useTheme } from '../theme';
import {
  LayoutDashboard, FolderKanban, Eye, ShieldCheck, FileText,
  Plus, Sun, Moon, ArrowRightLeft, AlertTriangle, CheckCircle2
} from 'lucide-react';

export default function AppLayout() {
  const { theme, toggle } = useTheme();
  const { jobId } = useParams();

  return (
    <div className="app-layout">
      {/* ── Sidebar ─────────────────────────────────────── */}
      <aside className="app-sidebar">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">M</div>
          <span className="sidebar-logo-text">Migration Platform</span>
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

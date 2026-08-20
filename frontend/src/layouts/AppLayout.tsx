import React, { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useParams, useLocation } from 'react-router-dom';
import { useTheme } from '../theme';
import { useUI } from '../store';
import {
  LayoutDashboard,
  FolderKanban,
  Plus,
  Sun,
  Moon,
  History,
  PanelLeftClose,
  PanelLeft,
  Search,
} from 'lucide-react';
import { api } from '../api';
import CommandPalette from '../components/CommandPalette';

export default function AppLayout() {
  const { theme, toggle } = useTheme();
  const {
    sidebarCollapsed,
    toggleSidebar,
    setCommandPaletteOpen,
  } = useUI();
  const { jobId } = useParams();
  const location = useLocation();
  const [reviewCount, setReviewCount] = useState<number | null>(null);
  const [jobName, setJobName] = useState<string | null>(null);

  // Fetch job name and issue count if active job
  useEffect(() => {
    if (jobId) {
      api.getJob(jobId)
        .then((j) => setJobName(j.name))
        .catch(() => setJobName(null));
      api.getReviewTasks(jobId, 'pending')
        .then((res) => {
          setReviewCount(res.total);
        })
        .catch(() => setReviewCount(null));
    } else {
      setJobName(null);
      setReviewCount(null);
    }
  }, [jobId]);

  // Compute breadcrumbs
  const getBreadcrumbs = () => {
    const path = location.pathname;
    const parts = [{ label: 'Migration Workspace', to: '/' }];

    if (path === '/jobs/new') {
      parts.push({ label: 'New Migration Wizard', to: '/jobs/new' });
    } else if (jobId) {
      const jobLabel = jobName || `Job: ${jobId.slice(0, 8)}...`;
      parts.push({ label: jobLabel, to: `/jobs/${jobId}` });
      if (path.includes('/execution')) {
        parts.push({ label: 'Live Execution Monitor', to: `/jobs/${jobId}/execution` });
      } else if (path.includes('/objects')) {
        parts.push({ label: 'Object Catalog', to: `/jobs/${jobId}/objects` });
      } else if (path.includes('/lineage')) {
        parts.push({ label: 'Lineage Explorer', to: `/jobs/${jobId}/lineage` });
      } else if (path.includes('/semantic')) {
        parts.push({ label: 'Semantic Model', to: `/jobs/${jobId}/semantic` });
      } else if (path.includes('/logic')) {
        parts.push({ label: 'Logic & Calculations', to: `/jobs/${jobId}/logic` });
      } else if (path.includes('/validation')) {
        parts.push({ label: 'Validation Center', to: `/jobs/${jobId}/validation` });
      } else if (path.includes('/review')) {
        parts.push({ label: 'Issue Center', to: `/jobs/${jobId}/review` });
      } else if (path.includes('/dashboards')) {
        parts.push({ label: 'Dashboard Inventory', to: `/jobs/${jobId}/dashboards` });
      } else if (path.includes('/exports')) {
        parts.push({ label: 'Export Center', to: `/jobs/${jobId}/exports` });
      } else if (path.includes('/audit')) {
        parts.push({ label: 'Audit Trail', to: `/jobs/${jobId}/audit` });
      } else if (path.includes('/report')) {
        parts.push({ label: 'Migration Report', to: `/jobs/${jobId}/report` });
      }
    }

    return parts;
  };

  const breadcrumbs = getBreadcrumbs();

  return (
    <div className={`app-layout ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      {/* ── Sidebar ─────────────────────────────────────── */}
      <aside className="app-sidebar">
        <div
          className="sidebar-header"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '16px 14px',
            borderBottom: '1px solid var(--line)',
            marginBottom: '12px',
          }}
        >
          <Link to="/" style={{ textDecoration: 'none', display: 'flex', alignItems: 'center' }}>
            <div className="sidebar-logo-icon sidebar-brand-icon">M</div>
            {!sidebarCollapsed && (
              <div className="sidebar-header-text" style={{ marginLeft: 8 }}>
                <div className="sidebar-logo-text">MSTR → Tableau</div>
                <div style={{ fontSize: 10, color: 'var(--ink-3)', fontWeight: 500 }}>
                  Control Center
                </div>
              </div>
            )}
          </Link>

          <button
            type="button"
            className="sidebar-toggle-btn"
            onClick={toggleSidebar}
            title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? <PanelLeft size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>



        {/* Global Navigation */}
        <p className="sidebar-section-label nav-section-title">Workspace</p>
        <nav className="sidebar-nav">
          <NavLink
            to="/"
            end
            className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`}
            title={sidebarCollapsed ? 'Overview' : undefined}
          >
            <LayoutDashboard size={16} className="icon" />
            <span className="sidebar-text">Overview</span>
          </NavLink>

          <NavLink
            to="/jobs/new"
            className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`}
            title={sidebarCollapsed ? 'New Migration' : undefined}
          >
            <Plus size={16} className="icon" />
            <span className="sidebar-text">New Migration</span>
          </NavLink>
        </nav>

        {/* Contextual Job Navigation */}
        {jobId && (
          <>
            <p className="sidebar-section-label nav-section-title" style={{ marginTop: 16 }}>
              Current Migration
            </p>
            <nav className="sidebar-nav">
              <NavLink
                to={`/jobs/${jobId}`}
                end
                className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`}
                title={sidebarCollapsed ? 'Migration Overview' : undefined}
              >
                <FolderKanban size={16} className="icon" />
                <span className="sidebar-text">Overview</span>
              </NavLink>

              <NavLink
                to={`/jobs/${jobId}/audit`}
                className={({ isActive }) => `sidebar-nav-item ${isActive ? 'active' : ''}`}
                title={sidebarCollapsed ? 'Audit Trail' : undefined}
              >
                <History size={16} className="icon" />
                <span className="sidebar-text">Audit Trail</span>
              </NavLink>
            </nav>
          </>
        )}

        {/* Bottom Section */}
        <div style={{ marginTop: 'auto', paddingTop: 16 }}>


          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: sidebarCollapsed ? 'center' : 'space-between',
              padding: sidebarCollapsed ? '8px 0' : '0 12px',
            }}
          >
            {!sidebarCollapsed && (
              <span style={{ fontSize: 11, color: 'var(--ink-3)', fontWeight: 500 }}>
                Theme
              </span>
            )}
            <div className="theme-toggle">
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
        </div>
      </aside>

      {/* ── Main Content Area ───────────────────────────── */}
      <div className="app-main">
        {/* Top bar with Breadcrumbs & Command Search */}
        <header className="app-topbar">
          <div className="breadcrumbs">
            {breadcrumbs.map((crumb, idx) => {
              const isLast = idx === breadcrumbs.length - 1;
              return (
                <React.Fragment key={crumb.to}>
                  {idx > 0 && <span className="breadcrumb-separator">/</span>}
                  {isLast ? (
                    <span className="breadcrumb-item active">{crumb.label}</span>
                  ) : (
                    <Link to={crumb.to} className="breadcrumb-item">
                      {crumb.label}
                    </Link>
                  )}
                </React.Fragment>
              );
            })}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <button
              type="button"
              className="search-command-btn"
              onClick={() => setCommandPaletteOpen(true)}
            >
              <Search size={14} />
              <span>Search or jump to...</span>
              <kbd className="kbd-shortcut">⌘K</kbd>
            </button>
          </div>
        </header>

        <main className="app-content">
          <Outlet />
        </main>
      </div>

      {/* Command Palette Overlay */}
      <CommandPalette />
    </div>
  );
}

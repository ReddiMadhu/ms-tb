import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Search,
  LayoutDashboard,
  PlusCircle,
  ShieldCheck,
  AlertTriangle,
  FolderOpen,
  GitBranch,
  Layers,
  Code,
  Download,
  History,
  FileText,
  Sun,
  Moon,
  ToggleLeft,
} from 'lucide-react';
import { useUI } from '../store';
import { useTheme } from '../theme';

interface CommandItem {
  id: string;
  label: string;
  category: string;
  icon: React.ReactNode;
  action: () => void;
  shortcut?: string;
}

export const CommandPalette: React.FC = () => {
  const { commandPaletteOpen, setCommandPaletteOpen } = useUI();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Extract active jobId if current route is inside a job
  const jobMatch = location.pathname.match(/\/jobs\/([a-zA-Z0-9_-]+)/);
  const activeJobId = jobMatch && jobMatch[1] !== 'new' ? jobMatch[1] : null;

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
      if (e.key === 'Escape' && commandPaletteOpen) {
        setCommandPaletteOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [commandPaletteOpen, setCommandPaletteOpen]);

  useEffect(() => {
    if (commandPaletteOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
      setSelectedIndex(0);
    } else {
      setQuery('');
    }
  }, [commandPaletteOpen]);

  if (!commandPaletteOpen) return null;

  const COMMANDS: CommandItem[] = [
    // General Navigation
    {
      id: 'nav-overview',
      label: 'Go to Overview Dashboard',
      category: 'Navigation',
      icon: <LayoutDashboard size={16} />,
      action: () => {
        navigate('/');
        setCommandPaletteOpen(false);
      },
    },
    {
      id: 'nav-new-job',
      label: 'Create New Migration Job',
      category: 'Navigation',
      icon: <PlusCircle size={16} />,
      action: () => {
        navigate('/jobs/new');
        setCommandPaletteOpen(false);
      },
    },

    // Contextual Job Navigation (if inside a job)
    ...(activeJobId
      ? [
        {
          id: 'job-overview',
          label: 'Migration Overview & Pipeline',
          category: 'Current Job',
          icon: <LayoutDashboard size={16} />,
          action: () => {
            navigate(`/jobs/${activeJobId}`);
            setCommandPaletteOpen(false);
          },
        },
        {
          id: 'job-execution',
          label: 'Live Execution Monitor',
          category: 'Current Job',
          icon: <Code size={16} />,
          action: () => {
            navigate(`/jobs/${activeJobId}/execution`);
            setCommandPaletteOpen(false);
          },
        },
        {
          id: 'job-objects',
          label: 'Discovered Object Catalog',
          category: 'Current Job',
          icon: <FolderOpen size={16} />,
          action: () => {
            navigate(`/jobs/${activeJobId}/objects`);
            setCommandPaletteOpen(false);
          },
        },
        {
          id: 'job-validation',
          label: 'Validation Center & Matrix',
          category: 'Current Job',
          icon: <ShieldCheck size={16} />,
          action: () => {
            navigate(`/jobs/${activeJobId}/validation`);
            setCommandPaletteOpen(false);
          },
        },
        {
          id: 'job-review',
          label: 'Issue Center & Ambiguity Queue',
          category: 'Current Job',
          icon: <AlertTriangle size={16} />,
          action: () => {
            navigate(`/jobs/${activeJobId}/review`);
            setCommandPaletteOpen(false);
          },
        },
        {
          id: 'job-lineage',
          label: 'Lineage & Cross-Reference Explorer',
          category: 'Current Job',
          icon: <GitBranch size={16} />,
          action: () => {
            navigate(`/jobs/${activeJobId}/lineage`);
            setCommandPaletteOpen(false);
          },
        },
        {
          id: 'job-semantic',
          label: 'Semantic Data Model',
          category: 'Current Job',
          icon: <Layers size={16} />,
          action: () => {
            navigate(`/jobs/${activeJobId}/semantic`);
            setCommandPaletteOpen(false);
          },
        },
        {
          id: 'job-logic',
          label: 'Logic & Calculation Translator',
          category: 'Current Job',
          icon: <Code size={16} />,
          action: () => {
            navigate(`/jobs/${activeJobId}/logic`);
            setCommandPaletteOpen(false);
          },
        },
        {
          id: 'job-dashboards',
          label: 'Dashboard Inventory',
          category: 'Current Job',
          icon: <LayoutDashboard size={16} />,
          action: () => {
            navigate(`/jobs/${activeJobId}/dashboards`);
            setCommandPaletteOpen(false);
          },
        },
        {
          id: 'job-exports',
          label: 'Export Center & Artifacts',
          category: 'Current Job',
          icon: <Download size={16} />,
          action: () => {
            navigate(`/jobs/${activeJobId}/exports`);
            setCommandPaletteOpen(false);
          },
        },
        {
          id: 'job-audit',
          label: 'Audit Trail & Execution Log',
          category: 'Current Job',
          icon: <History size={16} />,
          action: () => {
            navigate(`/jobs/${activeJobId}/audit`);
            setCommandPaletteOpen(false);
          },
        },
        {
          id: 'job-report',
          label: 'Generate Migration Report',
          category: 'Current Job',
          icon: <FileText size={16} />,
          action: () => {
            navigate(`/jobs/${activeJobId}/report`);
            setCommandPaletteOpen(false);
          },
        },
      ]
      : []),

    // Preferences
    {
      id: 'pref-theme',
      label: `Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Theme`,
      category: 'Preferences',
      icon: theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />,
      action: () => {
        toggle();
        setCommandPaletteOpen(false);
      },
    },
  ];

  const filteredCommands = COMMANDS.filter(
    (c) =>
      c.label.toLowerCase().includes(query.toLowerCase()) ||
      c.category.toLowerCase().includes(query.toLowerCase())
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % Math.max(1, filteredCommands.length));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) =>
        prev - 1 < 0 ? Math.max(0, filteredCommands.length - 1) : prev - 1
      );
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filteredCommands[selectedIndex]) {
        filteredCommands[selectedIndex].action();
      }
    }
  };

  return (
    <div className="command-palette-backdrop" onClick={() => setCommandPaletteOpen(false)}>
      <div className="command-palette-modal" onClick={(e) => e.stopPropagation()}>
        <div className="command-palette-input-wrap">
          <Search size={18} color="var(--ink-3)" />
          <input
            ref={inputRef}
            className="command-palette-input"
            placeholder="Type a command or search destination..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={handleKeyDown}
          />
          <kbd className="kbd-shortcut">ESC</kbd>
        </div>

        <div className="command-palette-results">
          {filteredCommands.length === 0 ? (
            <div
              style={{
                padding: '24px',
                textAlign: 'center',
                color: 'var(--ink-3)',
                fontSize: '0.875rem',
              }}
            >
              No matching commands found.
            </div>
          ) : (
            filteredCommands.map((cmd, idx) => {
              const isSelected = idx === selectedIndex;
              return (
                <div
                  key={cmd.id}
                  className={`command-palette-item ${isSelected ? 'selected' : ''}`}
                  onClick={cmd.action}
                  onMouseEnter={() => setSelectedIndex(idx)}
                >
                  <div className="command-palette-item-left">
                    <span style={{ color: isSelected ? 'var(--primary)' : 'var(--ink-2)' }}>
                      {cmd.icon}
                    </span>
                    <span>{cmd.label}</span>
                  </div>
                  <span
                    style={{
                      fontSize: '0.6875rem',
                      color: 'var(--ink-3)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.04em',
                    }}
                  >
                    {cmd.category}
                  </span>
                </div>
              );
            })
          )}
        </div>

        <div className="command-palette-footer">
          <span>↑↓ Navigate</span>
          <span>↵ Select</span>
          <span>ESC Close</span>
        </div>
      </div>
    </div>
  );
};

export default CommandPalette;

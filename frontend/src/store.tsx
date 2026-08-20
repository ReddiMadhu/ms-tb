import React, { createContext, useContext, useState } from 'react';

export interface UIState {
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (v: boolean) => void;
  toggleSidebar: () => void;
  viewMode: 'business' | 'technical';
  setViewMode: (v: 'business' | 'technical') => void;
  toggleViewMode: () => void;
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (v: boolean) => void;
}

const UIContext = createContext<UIState | undefined>(undefined);

export const UIProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [viewMode, setViewMode] = useState<'business' | 'technical'>('technical');
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

  const toggleSidebar = () => setSidebarCollapsed((prev) => !prev);
  const toggleViewMode = () => setViewMode((prev) => (prev === 'business' ? 'technical' : 'business'));

  return (
    <UIContext.Provider
      value={{
        sidebarCollapsed,
        setSidebarCollapsed,
        toggleSidebar,
        viewMode,
        setViewMode,
        toggleViewMode,
        commandPaletteOpen,
        setCommandPaletteOpen,
      }}
    >
      {children}
    </UIContext.Provider>
  );
};

export const useUI = (): UIState => {
  const context = useContext(UIContext);
  if (!context) {
    throw new Error('useUI must be used within a UIProvider');
  }
  return context;
};

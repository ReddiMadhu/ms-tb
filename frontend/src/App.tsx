import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './theme';
import { UIProvider } from './store';
import AppLayout from './layouts/AppLayout';

import Dashboard from './pages/Dashboard';
import NewJob from './pages/NewJob';
import JobDetail from './pages/JobDetail';
import LiveExecution from './pages/LiveExecution';
import Objects from './pages/Objects';
import ObjectDetail from './pages/ObjectDetail';
import LogicExplorer from './pages/LogicExplorer';
import DashboardInventory from './pages/DashboardInventory';
import ExportCenter from './pages/ExportCenter';
import AuditTrail from './pages/AuditTrail';

import './index.css';

export default function App() {
  return (
    <ThemeProvider>
      <UIProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              {/* Workspace Navigation */}
              <Route index element={<Dashboard />} />
              <Route path="jobs/new" element={<NewJob />} />

              {/* Migration Control Center Sub-pages */}
              <Route path="jobs/:jobId" element={<JobDetail />} />
              <Route path="jobs/:jobId/execution" element={<LiveExecution />} />
              <Route path="jobs/:jobId/objects" element={<Objects />} />
              <Route path="jobs/:jobId/objects/:objId" element={<ObjectDetail />} />
              <Route path="jobs/:jobId/semantic" element={<Navigate to="../logic" replace />} />
              <Route path="jobs/:jobId/logic" element={<LogicExplorer />} />
              <Route path="jobs/:jobId/review" element={<Navigate to="../exports" replace />} />
              <Route path="jobs/:jobId/dashboards" element={<DashboardInventory />} />
              <Route path="jobs/:jobId/exports" element={<ExportCenter />} />
              <Route path="jobs/:jobId/audit" element={<AuditTrail />} />
              <Route path="jobs/:jobId/report" element={<Navigate to="../exports" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </UIProvider>
    </ThemeProvider>
  );
}

import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from './theme';
import AppLayout from './layouts/AppLayout';
import Dashboard from './pages/Dashboard';
import NewJob from './pages/NewJob';
import JobDetail from './pages/JobDetail';
import Objects from './pages/Objects';
import ReviewQueue from './pages/ReviewQueue';
import Validation from './pages/Validation';

import './index.css';

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="jobs/new" element={<NewJob />} />
            <Route path="jobs/:jobId" element={<JobDetail />} />
            <Route path="jobs/:jobId/objects" element={<Objects />} />
            <Route path="jobs/:jobId/review" element={<ReviewQueue />} />
            <Route path="jobs/:jobId/validation" element={<Validation />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}

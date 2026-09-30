import { Navigate, Route, Routes } from 'react-router-dom';
import { ProtectedRoute } from './routes/ProtectedRoute';
import { AppLayout } from './layouts/AppLayout';
import { CaseLayout } from './layouts/CaseLayout';
import { LoginPage } from './pages/LoginPage';
import { ResourcePage } from './pages/ResourcePage';
import { FileUploader } from './components/FileUploader';

const notif = <ResourcePage title="Notifications" resource="notifications" empty="No notifications." />;
const cases = <ResourcePage title="Cases" resource="cases" empty="No cases found." />;
const caseOverview = <ResourcePage title="Case overview" resource="case" empty="No case information available." loadingLabel="Loading case information…" />;
const timeline = <ResourcePage title="Timeline" resource="timeline" empty="No timeline events yet." />;

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<LoginPage />} />

      <Route path="/lawyer" element={<ProtectedRoute role="LAWYER"><AppLayout role="LAWYER" /></ProtectedRoute>}>
        <Route path="dashboard" element={<ResourcePage title="Dashboard" resource="dashboard" empty="No cases found." />} />
        <Route path="cases" element={cases} />
        <Route path="notifications" element={notif} />
        <Route path="cases/:caseId" element={<CaseLayout role="LAWYER" />}>
          <Route index element={caseOverview} />
          <Route path="evidence" element={<ResourcePage title="Evidence" resource="evidence" empty="No evidence has been uploaded for this case." before={(id) => <FileUploader caseId={id} />} />} />
          <Route path="conflicts" element={<ResourcePage title="Conflicts" resource="conflicts" empty="No conflicts reported for this case." />} />
          <Route path="missing-evidence" element={<ResourcePage title="Missing evidence" resource="missingEvidence" empty="No missing evidence reported." />} />
          <Route path="reasoning" element={<ResourcePage title="Reasoning" resource="reasoning" empty="No reasoning run available." />} />
          <Route path="timeline" element={timeline} />
          <Route path="evolution" element={<ResourcePage title="Case evolution" resource="evolution" empty="No version history yet." />} />
        </Route>
      </Route>

      <Route path="/guardian" element={<ProtectedRoute role="GUARDIAN"><AppLayout role="GUARDIAN" /></ProtectedRoute>}>
        <Route path="dashboard" element={<ResourcePage title="Dashboard" resource="dashboard" empty="No cases found." />} />
        <Route path="cases" element={cases} />
        <Route path="documents" element={<ResourcePage title="Shared documents" resource="documents" empty="No documents have been shared with you." />} />
        <Route path="notifications" element={notif} />
        <Route path="cases/:caseId" element={<CaseLayout role="GUARDIAN" />}>
          <Route index element={caseOverview} />
          <Route path="status" element={<ResourcePage title="Case status" resource="status" empty="No status update available." />} />
          <Route path="timeline" element={timeline} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}

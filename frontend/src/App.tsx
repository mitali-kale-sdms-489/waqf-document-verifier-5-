import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { Login } from "@/pages/Login";
import { Dashboard } from "@/pages/Dashboard";
import { Upload } from "@/pages/Upload";
import { Review } from "@/pages/Review";
import { Reports } from "@/pages/Reports";
import { Admin } from "@/pages/Admin";
import { Settings } from "@/pages/Settings";

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<Dashboard />} />
        <Route
          path="/upload"
          element={
            <ProtectedRoute allowedRoles={["USER"]}>
              <Upload />
            </ProtectedRoute>
          }
        />
        <Route path="/settings" element={<Settings />} />
        <Route
          path="/review"
          element={
            <ProtectedRoute allowedRoles={["SUPERVISOR"]}>
              <Review />
            </ProtectedRoute>
          }
        />
        <Route
          path="/review/:documentId"
          element={
            <ProtectedRoute allowedRoles={["SUPERVISOR"]}>
              <Review />
            </ProtectedRoute>
          }
        />
        <Route
          path="/reports"
          element={
            <ProtectedRoute allowedRoles={["SUPERVISOR"]}>
              <Reports />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <ProtectedRoute allowedRoles={["SUPERVISOR"]}>
              <Admin />
            </ProtectedRoute>
          }
        />
      </Route>

      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export default App;

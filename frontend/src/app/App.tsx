import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./providers/AuthProvider";
import { LoginPage } from "../pages/login/LoginPage";
import { AssignmentsPage } from "../pages/assignments/AssignmentsPage";
import { AssignmentDetailsPage } from "../pages/assignment-details/AssignmentDetailsPage";

function ProtectedRoute({ children }: { children: JSX.Element }) {
  const { isAuthenticated } = useAuth();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/assignments"
          element={
            <ProtectedRoute>
              <AssignmentsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/assignments/:assignmentId"
          element={
            <ProtectedRoute>
              <AssignmentDetailsPage />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/assignments" replace />} />
      </Routes>
    </AuthProvider>
  );
}

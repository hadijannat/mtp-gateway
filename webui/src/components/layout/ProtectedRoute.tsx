import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../../store/authStore';
import { Loader2 } from 'lucide-react';

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredPermission?: string;
}

export default function ProtectedRoute({ children, requiredPermission }: ProtectedRouteProps) {
  const location = useLocation();
  const { isAuthenticated, isLoading, user } = useAuthStore();

  // Show loading while checking auth
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg-primary">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 text-accent-primary animate-spin" />
          <span className="text-text-secondary">Loading...</span>
        </div>
      </div>
    );
  }

  // Redirect to login if not authenticated
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Check permission if required
  if (requiredPermission && user) {
    const hasPermission = user.permissions.includes(requiredPermission);
    if (!hasPermission) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-bg-primary">
          <div className="card p-8 text-center">
            <h1 className="text-xl font-bold text-status-alarm mb-2">Access Denied</h1>
            <p className="text-text-secondary">
              You don't have permission to access this page.
            </p>
            <p className="text-text-muted text-sm mt-2">
              Required: {requiredPermission}
            </p>
          </div>
        </div>
      );
    }
  }

  return <>{children}</>;
}

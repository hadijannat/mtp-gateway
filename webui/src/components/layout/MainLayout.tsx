import { useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Cog,
  Bell,
  Activity,
  LogOut,
  Menu,
  X,
  ChevronDown,
  User,
} from 'lucide-react';
import { useAuthStore } from '../../store/authStore';
import AlarmBanner from '../alarms/AlarmBanner';

const navigation = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
  { name: 'Services', href: '/services', icon: Cog },
  { name: 'Alarms', href: '/alarms', icon: Bell },
  { name: 'Trends', href: '/trends', icon: Activity },
];

export default function MainLayout() {
  const location = useLocation();
  const { user, logout } = useAuthStore();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  const handleLogout = () => {
    logout();
  };

  return (
    <div className="min-h-screen bg-bg-primary flex">
      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-50 w-64 bg-bg-secondary border-r border-border-default
          transform transition-transform duration-200 ease-in-out
          lg:translate-x-0 lg:static lg:z-auto
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        {/* Logo */}
        <div className="h-16 flex items-center justify-between px-4 border-b border-border-default">
          <Link to="/" className="flex items-center gap-2">
            <div className="w-8 h-8 rounded bg-accent-primary flex items-center justify-center">
              <span className="text-white font-bold text-sm">MTP</span>
            </div>
            <span className="font-semibold text-text-primary">Gateway</span>
          </Link>
          <button
            onClick={() => setSidebarOpen(false)}
            className="lg:hidden p-1 text-text-muted hover:text-text-primary"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="p-4 space-y-1">
          {navigation.map((item) => {
            const isActive = location.pathname === item.href;
            const Icon = item.icon;

            return (
              <Link
                key={item.name}
                to={item.href}
                onClick={() => setSidebarOpen(false)}
                className={`
                  flex items-center gap-3 px-3 py-2 rounded-lg transition-colors
                  ${
                    isActive
                      ? 'bg-accent-primary/20 text-accent-primary'
                      : 'text-text-secondary hover:bg-bg-tertiary hover:text-text-primary'
                  }
                `}
              >
                <Icon className="w-5 h-5" />
                <span>{item.name}</span>
              </Link>
            );
          })}
        </nav>

        {/* System status (bottom) */}
        <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-border-default">
          <div className="flex items-center gap-2 text-sm">
            <div className="w-2 h-2 rounded-full bg-status-good" />
            <span className="text-text-secondary">System Online</span>
          </div>
        </div>
      </aside>

      {/* Main content area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="h-16 bg-bg-secondary border-b border-border-default flex items-center justify-between px-4">
          {/* Mobile menu button */}
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden p-2 text-text-muted hover:text-text-primary"
          >
            <Menu className="w-6 h-6" />
          </button>

          {/* Page title (desktop) */}
          <div className="hidden lg:block">
            <h1 className="text-lg font-semibold text-text-primary">
              {navigation.find((n) => n.href === location.pathname)?.name ?? 'Dashboard'}
            </h1>
          </div>

          {/* Right side */}
          <div className="flex items-center gap-4">
            {/* Alarm indicator */}
            <Link
              to="/alarms"
              className="relative p-2 text-text-muted hover:text-text-primary"
            >
              <Bell className="w-5 h-5" />
              {/* Active alarm badge */}
              <span className="absolute top-1 right-1 w-2 h-2 bg-status-alarm rounded-full alarm-active" />
            </Link>

            {/* User menu */}
            <div className="relative">
              <button
                onClick={() => setUserMenuOpen(!userMenuOpen)}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-bg-tertiary transition-colors"
              >
                <div className="w-8 h-8 rounded-full bg-accent-primary/20 flex items-center justify-center">
                  <User className="w-4 h-4 text-accent-primary" />
                </div>
                <span className="text-sm text-text-primary hidden sm:block">
                  {user?.username}
                </span>
                <ChevronDown className="w-4 h-4 text-text-muted" />
              </button>

              {/* Dropdown */}
              {userMenuOpen && (
                <>
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setUserMenuOpen(false)}
                  />
                  <div className="absolute right-0 mt-2 w-48 bg-bg-secondary border border-border-default rounded-lg shadow-lg z-50">
                    <div className="p-3 border-b border-border-default">
                      <p className="text-sm font-medium text-text-primary">{user?.username}</p>
                      <p className="text-xs text-text-muted capitalize">{user?.role}</p>
                    </div>
                    <div className="p-1">
                      <button
                        onClick={handleLogout}
                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:bg-bg-tertiary rounded transition-colors"
                      >
                        <LogOut className="w-4 h-4" />
                        Sign Out
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </header>

        {/* Alarm banner */}
        <AlarmBanner />

        {/* Page content */}
        <main className="flex-1 p-4 lg:p-6 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

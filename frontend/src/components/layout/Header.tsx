import { NavLink, useNavigate } from "react-router-dom";
import { Bell, ChevronDown, LogOut, ScrollText, Settings, User } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useSessionTimer } from "@/hooks/useSessionTimer";
import { ROLE_BADGE_VARIANT, ROLE_LABELS, ROLE_NAV_ITEMS } from "@/config/navigation";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";

const SESSION_SECONDS = 15 * 60; // 15 minutes, mirrors a typical JWT access-token TTL

const MOCK_NOTIFICATIONS = [
  { id: "1", text: "3 documents flagged for review", href: "/review" },
  { id: "2", text: "Seeded-error benchmark completed", href: "/reports" },
];

export function Header() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const { formatted, secondsLeft } = useSessionTimer(SESSION_SECONDS, () => {
    toast.error("Session expired — please sign in again.");
    logout();
    navigate("/login");
  });

  if (!user) return null;

  const navItems = ROLE_NAV_ITEMS[user.role] ?? [];
  const isSessionLow = secondsLeft <= 60;

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <header className="h-16 shrink-0 border-b border-border bg-card flex items-center px-6 gap-8">
      <div className="flex items-center gap-2 shrink-0">
        <ScrollText className="h-5 w-5 text-primary" strokeWidth={1.75} />
        <span className="font-display text-lg leading-none">Waqf DocVerify</span>
      </div>

      <nav className="flex items-center gap-1 flex-1">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )
            }
          >
            <Icon className="h-4 w-4" strokeWidth={1.75} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="flex items-center gap-4 shrink-0">
        {/* Session timer */}
        <span
          className={cn(
            "font-tabular text-xs px-2 py-1 rounded border",
            isSessionLow
              ? "border-rust/30 bg-rust/10 text-rust"
              : "border-border text-muted-foreground"
          )}
          title="Time remaining in this session"
        >
          {formatted}
        </span>

        {/* Notifications */}
        <DropdownMenu>
          <DropdownMenuTrigger className="relative rounded-md p-2 hover:bg-muted outline-none">
            <Bell className="h-4.5 w-4.5 text-muted-foreground" strokeWidth={1.75} />
            {MOCK_NOTIFICATIONS.length > 0 && (
              <span className="absolute top-1 right-1 flex h-4 w-4 items-center justify-center rounded-full bg-rust text-[10px] font-semibold text-white">
                {MOCK_NOTIFICATIONS.length}
              </span>
            )}
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Notifications</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {MOCK_NOTIFICATIONS.map((n) => (
              <DropdownMenuItem key={n.id} onSelect={() => navigate(n.href)}>
                {n.text}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* User menu */}
        <DropdownMenu>
          <DropdownMenuTrigger className="flex items-center gap-2 rounded-md pl-1 pr-2 py-1 outline-none hover:bg-muted">
            <Avatar fullName={user.full_name} />
            <div className="hidden md:flex flex-col items-start leading-tight">
              <span className="text-sm font-medium">{user.full_name}</span>
              <Badge variant={ROLE_BADGE_VARIANT[user.role]} className="mt-0.5">
                {ROLE_LABELS[user.role]}
              </Badge>
            </div>
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>{user.email}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => toast("Profile settings coming soon")}>
              <User className="h-4 w-4" /> Profile
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => navigate("/settings")}>
              <Settings className="h-4 w-4" /> Settings
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={handleLogout} className="text-rust focus:bg-rust/10">
              <LogOut className="h-4 w-4" /> Logout
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}

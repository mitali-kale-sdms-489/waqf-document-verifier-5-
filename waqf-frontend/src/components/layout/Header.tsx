import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { Bell, ChevronDown, LogOut, ScrollText, Settings, User } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { ROLE_BADGE_VARIANT, ROLE_LABELS, ROLE_NAV_ITEMS } from "@/config/navigation";
import { getAllDocuments } from "@/api/documents";
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

interface DocNotification {
  id: string;
  text: string;
  href: string;
}

/** Bell only lights up for documents the supervisor has actually acted on.
 *  The review endpoint sets status to "reviewed" on approve/correct and
 *  "flagged" on flag — "approved" is a legacy status the review flow never
 *  actually produces, so both real values are checked here. */
const NOTIFIABLE_STATUSES = new Set(["reviewed", "approved", "flagged"]);

export function Header() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState<DocNotification[]>([]);
  // Ids the supervisor has dismissed via "Clear". Lives only in component
  // state (not localStorage/sessionStorage), so it's naturally wiped every
  // time Header remounts — i.e. every fresh login — matching "refresh on
  // every new login" without needing to persist or manually reset anything.
  const [clearedIds, setClearedIds] = useState<Set<string>>(new Set());


  // Supervisor-only: pull real documents and surface only the ones that
  // were actually approved or flagged, newest first, clicking one goes
  // straight to that document's review screen.
  useEffect(() => {
    if (!user || user.role !== "SUPERVISOR") return;
    let cancelled = false;

    getAllDocuments()
      .then((docs) => {
        if (cancelled) return;
        const relevant = docs
          .filter((doc) => NOTIFIABLE_STATUSES.has(doc.status))
          .sort((a, b) => new Date(b.uploadedAt).getTime() - new Date(a.uploadedAt).getTime())
          .slice(0, 8)
          .map((doc) => ({
            id: doc.id,
            text:
              doc.status === "flagged"
                ? `${doc.filename} was flagged for review`
                : `${doc.filename} was approved`,
            href: `/review/${doc.id}`,
          }));
        setNotifications(relevant);
        setClearedIds(new Set()); // fresh login/session → nothing cleared yet
      })
      .catch(() => {
        if (!cancelled) setNotifications([]);
      });

    return () => {
      cancelled = true;
    };
  }, [user]);

  if (!user) return null;

  const navItems = ROLE_NAV_ITEMS[user.role] ?? [];
  const visibleNotifications = notifications.filter((n) => !clearedIds.has(n.id));

  function handleLogout() {
    logout();
    navigate("/login");
  }

  function handleClearNotifications() {
    setClearedIds(new Set(notifications.map((n) => n.id)));
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
        {/* Notifications — supervisor only, driven by real approve/flag actions */}
        {user.role === "SUPERVISOR" && (
          <DropdownMenu>
            <DropdownMenuTrigger className="relative rounded-md p-2 hover:bg-muted outline-none">
              <Bell className="h-4.5 w-4.5 text-muted-foreground" strokeWidth={1.75} />
              {visibleNotifications.length > 0 && (
                <span className="absolute top-1 right-1 flex h-4 w-4 items-center justify-center rounded-full bg-rust text-[10px] font-semibold text-white">
                  {visibleNotifications.length}
                </span>
              )}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-72">
              <div className="flex items-center justify-between px-2 py-1.5">
                <DropdownMenuLabel className="p-0">Notifications</DropdownMenuLabel>
                {visibleNotifications.length > 0 && (
                  <button
                    type="button"
                    onClick={handleClearNotifications}
                    className="text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
                  >
                    Clear all
                  </button>
                )}
              </div>
              <DropdownMenuSeparator />
              {visibleNotifications.length > 0 ? (
                visibleNotifications.map((n) => (
                  <DropdownMenuItem key={n.id} onSelect={() => navigate(n.href)}>
                    {n.text}
                  </DropdownMenuItem>
                ))
              ) : (
                <DropdownMenuItem disabled>No new notifications</DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

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

import { useState } from "react";
import { NavLink } from "react-router-dom";
import { ChevronsLeft, ChevronsRight } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { ROLE_NAV_ITEMS } from "@/config/navigation";
import { cn } from "@/lib/utils";

export function Sidebar() {
  const { user } = useAuth();
  const [collapsed, setCollapsed] = useState(false);

  if (!user) return null;
  const navItems = ROLE_NAV_ITEMS[user.role] ?? [];

  return (
    <aside
      className={cn(
        "shrink-0 bg-primary text-primary-foreground flex flex-col transition-all duration-200",
        collapsed ? "w-16" : "w-56"
      )}
    >
      <div className={cn("flex px-2 pt-3 pb-1", collapsed ? "justify-center" : "justify-end")}>
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? "Expand" : "Collapse"}
          className="flex items-center justify-center rounded-md p-1.5 text-primary-foreground/50 hover:text-primary-foreground/80 hover:bg-primary-foreground/5 transition-colors"
        >
          {collapsed ? (
            <ChevronsRight className="h-4 w-4" strokeWidth={1.75} />
          ) : (
            <ChevronsLeft className="h-4 w-4" strokeWidth={1.75} />
          )}
        </button>
      </div>

      <nav className="flex-1 px-2 py-4 space-y-1">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            title={collapsed ? label : undefined}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors border-l-2",
                collapsed && "justify-center px-0",
                isActive
                  ? "bg-primary-foreground/10 border-accent text-primary-foreground"
                  : "border-transparent text-primary-foreground/70 hover:bg-primary-foreground/5 hover:text-primary-foreground"
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
            {!collapsed && label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}

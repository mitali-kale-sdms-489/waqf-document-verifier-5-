import { Moon, Sun } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import { ROLE_LABELS } from "@/config/navigation";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

export function Settings() {
  const { user } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="font-display text-2xl">Settings</h1>
        <p className="text-sm text-muted-foreground">Manage your account and app preferences.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Account</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center gap-4">
          <Avatar fullName={user?.full_name ?? ""} />
          <div>
            <p className="text-sm font-medium">{user?.full_name}</p>
            <p className="text-xs text-muted-foreground">{user?.email}</p>
          </div>
          {user && (
            <Badge variant={user.role === "SUPERVISOR" ? "roleElevated" : "roleStandard"} className="ml-auto">
              {ROLE_LABELS[user.role]}
            </Badge>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Appearance</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                {isDark ? <Moon className="h-4.5 w-4.5" strokeWidth={1.75} /> : <Sun className="h-4.5 w-4.5" strokeWidth={1.75} />}
              </div>
              <div>
                <p className="text-sm font-medium">Dark mode</p>
                <p className="text-xs text-muted-foreground">
                  {isDark ? "Currently using the dark theme." : "Currently using the light theme."}
                </p>
              </div>
            </div>
            <Switch
              checked={isDark}
              onCheckedChange={toggleTheme}
              aria-label="Toggle dark mode"
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

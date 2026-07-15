import { useEffect, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import toast from "react-hot-toast";
import { Loader2, Plus, ShieldAlert, UserPlus } from "lucide-react";
import {
  createUser,
  getCerBenchmark,
  getOcrSettings,
  getUsers,
  getValidationRules,
  setUserActive,
  setValidationRuleEnabled,
  updateOcrSettings,
  updateUserRole,
  type AdminUser,
  type CerBenchmarkResult,
  type OcrSettings,
  type ValidationRuleConfig,
} from "@/api/admin";
import { ROLE_LABELS } from "@/config/navigation";
import type { Role } from "@/types/auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export function Admin() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl">Admin</h1>
        <p className="text-sm text-muted-foreground">
          User management, validation rules, and OCR engine configuration. Visible to the Supervisor role only.
        </p>
      </div>

      <Tabs defaultValue="users">
        <TabsList>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="rules">Validation rules</TabsTrigger>
          <TabsTrigger value="ocr">OCR settings</TabsTrigger>
          <TabsTrigger value="benchmark">OCR benchmark</TabsTrigger>
        </TabsList>

        <TabsContent value="users">
          <UsersPanel />
        </TabsContent>
        <TabsContent value="rules">
          <ValidationRulesPanel />
        </TabsContent>
        <TabsContent value="ocr">
          <OcrSettingsPanel />
        </TabsContent>
        <TabsContent value="benchmark">
          <CerBenchmarkPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

function UsersPanel() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState<Role>("USER");
  const [isSaving, setIsSaving] = useState(false);

  function reload() {
    setIsLoading(true);
    getUsers().then((u) => {
      setUsers(u);
      setIsLoading(false);
    });
  }

  useEffect(reload, []);

  async function handleRoleChange(id: number, role: Role) {
    setUsers((prev) => prev.map((u) => (u.id === id ? { ...u, role } : u)));
    await updateUserRole(id, role);
    toast.success("Role updated.");
  }

  async function handleActiveToggle(id: number, active: boolean) {
    setUsers((prev) => prev.map((u) => (u.id === id ? { ...u, active } : u)));
    await setUserActive(id, active);
    toast.success(active ? "User enabled." : "User disabled.");
  }

  async function handleCreateUser() {
    if (!newName.trim() || !newEmail.trim()) return;
    setIsSaving(true);
    try {
      const created = await createUser({ fullName: newName.trim(), email: newEmail.trim(), role: newRole });
      toast.success(
        `${newName.trim()} added. Temporary password: ${created.temporaryPassword} — copy this now, it won't be shown again.`,
        { duration: 15000 }
      );
      setDialogOpen(false);
      setNewName("");
      setNewEmail("");
      setNewRole("USER");
      reload();
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>Users</CardTitle>
          <CardDescription>Manage who can access the registry, upload, and review.</CardDescription>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button size="sm" className="gap-2">
              <UserPlus className="h-4 w-4" /> Add user
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add user</DialogTitle>
              <DialogDescription>Grant someone access to the registry.</DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="new-user-name">Full name</Label>
                <Input id="new-user-name" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Aisha Khan" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="new-user-email">Email</Label>
                <Input
                  id="new-user-email"
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  placeholder="name@waqf.gov.in"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Role</Label>
                <Select value={newRole} onValueChange={(v) => setNewRole(v as Role)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="USER">User — upload only</SelectItem>
                    <SelectItem value="SUPERVISOR">Supervisor — full access</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={isSaving}>
                Cancel
              </Button>
              <Button onClick={handleCreateUser} disabled={isSaving || !newName.trim() || !newEmail.trim()} className="gap-2">
                {isSaving && <Loader2 className="h-4 w-4 animate-spin" />}
                Add user
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading users…
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-t border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-6 py-3 font-medium">Name</th>
                  <th className="px-6 py-3 font-medium">Email</th>
                  <th className="px-6 py-3 font-medium">Role</th>
                  <th className="px-6 py-3 font-medium">Last login</th>
                  <th className="px-6 py-3 font-medium text-right">Active</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-t border-border hover:bg-muted/50">
                    <td className="px-6 py-3 font-medium">{u.fullName}</td>
                    <td className="px-6 py-3 text-muted-foreground font-tabular">{u.email}</td>
                    <td className="px-6 py-3">
                      <Select value={u.role} onValueChange={(v) => handleRoleChange(u.id, v as Role)}>
                        <SelectTrigger className="h-8 w-40 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="USER">{ROLE_LABELS.USER}</SelectItem>
                          <SelectItem value="SUPERVISOR">{ROLE_LABELS.SUPERVISOR}</SelectItem>
                        </SelectContent>
                      </Select>
                    </td>
                    <td className="px-6 py-3 text-muted-foreground font-tabular">
                      {u.lastLoginAt ? formatDistanceToNow(new Date(u.lastLoginAt), { addSuffix: true }) : "Never"}
                    </td>
                    <td className="px-6 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {u.active ? (
                          <Badge variant="success">Active</Badge>
                        ) : (
                          <Badge variant="outline">Disabled</Badge>
                        )}
                        <Switch checked={u.active} onCheckedChange={(checked) => handleActiveToggle(u.id, checked)} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Validation rules
// ---------------------------------------------------------------------------

function ValidationRulesPanel() {
  const [rules, setRules] = useState<ValidationRuleConfig[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    getValidationRules().then((r) => {
      setRules(r);
      setIsLoading(false);
    });
  }, []);

  async function toggle(key: string, enabled: boolean) {
    setRules((prev) => prev.map((r) => (r.key === key ? { ...r, enabled } : r)));
    await setValidationRuleEnabled(key, enabled);
    toast.success(enabled ? "Rule enabled." : "Rule disabled.");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Validation rules</CardTitle>
        <CardDescription>
          Rules run automatically after extraction and surface on the Review screen.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-1">
        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading rules…
          </div>
        ) : (
          rules.map((rule) => (
            <div
              key={rule.key}
              className="flex items-start justify-between gap-4 py-4 border-t border-border first:border-t-0"
            >
              <div className="flex items-start gap-3">
                <div
                  className={
                    rule.severity === "fail"
                      ? "mt-0.5 rounded-md bg-rust/15 p-1.5 text-rust"
                      : "mt-0.5 rounded-md bg-brass/15 p-1.5 text-brass"
                  }
                >
                  <ShieldAlert className="h-4 w-4" strokeWidth={1.75} />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium">{rule.name}</p>
                    <Badge variant={rule.severity === "fail" ? "danger" : "warning"} className="capitalize">
                      {rule.severity}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5 max-w-xl">{rule.description}</p>
                </div>
              </div>
              <Switch checked={rule.enabled} onCheckedChange={(checked) => toggle(rule.key, checked)} />
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// OCR settings
// ---------------------------------------------------------------------------

function OcrSettingsPanel() {
  const [settings, setSettings] = useState<OcrSettings | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    getOcrSettings().then((s) => {
      setSettings(s);
      setIsLoading(false);
    });
  }, []);

  async function patch(update: Partial<OcrSettings>) {
    if (!settings) return;
    const next = { ...settings, ...update };
    setSettings(next);
    await updateOcrSettings(update);
    toast.success("OCR settings saved.");
  }

  if (isLoading || !settings) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading OCR settings…
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>OCR &amp; extraction engine</CardTitle>
        <CardDescription>Controls how scans are read and scored before reaching the review queue.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-1.5 max-w-md">
          <Label>Primary extraction engine</Label>
          <div className="rounded-md border border-border bg-muted/40 px-3 py-2.5 text-sm">
            <span className="font-medium">Sarvam Vision 3B</span>
            <span className="text-muted-foreground"> — always tried first</span>
          </div>
          <p className="text-xs text-muted-foreground">
            Engine selection is automatic, not a manual choice: if Sarvam Vision's own read confidence falls
            below the fallback threshold below, Tesseract and Gemini Vision are both run too and whichever scores
            the highest confidence is used instead.
          </p>
        </div>

        <div className="space-y-1.5 max-w-sm border-t border-border pt-4">
          <Label htmlFor="fallback-threshold">OCR fallback threshold</Label>
          <Input
            id="fallback-threshold"
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={settings.ocrFallbackThreshold}
            onChange={(e) => patch({ ocrFallbackThreshold: Number(e.target.value) })}
            className="font-tabular max-w-[140px]"
          />
          <p className="text-xs text-muted-foreground">
            When Sarvam Vision's confidence is below this, Tesseract and Gemini Vision are compared against it
            automatically.
          </p>
        </div>

        <div className="flex items-center justify-between max-w-md border-t border-border pt-4">
          <div>
            <p className="text-sm font-medium">Reconcile against Tesseract</p>
            <p className="text-xs text-muted-foreground">
              Cross-checks the primary engine's output and reconciles disagreements before scoring.
            </p>
          </div>
          <Switch
            checked={settings.useReconciliation}
            onCheckedChange={(checked) => patch({ useReconciliation: checked })}
          />
        </div>

        <div className="flex items-center justify-between max-w-md border-t border-border pt-4">
          <div>
            <p className="text-sm font-medium">Auto-approve high-confidence records</p>
            <p className="text-xs text-muted-foreground">
              Skip manual review when every field clears the high-confidence threshold.
            </p>
          </div>
          <Switch
            checked={settings.autoApproveHighConfidence}
            onCheckedChange={(checked) => patch({ autoApproveHighConfidence: checked })}
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-md border-t border-border pt-4">
          <div className="space-y-1.5">
            <Label htmlFor="high-threshold">High-confidence threshold</Label>
            <Input
              id="high-threshold"
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={settings.highConfidenceThreshold}
              onChange={(e) => patch({ highConfidenceThreshold: Number(e.target.value) })}
              className="font-tabular"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="low-threshold">Low-confidence threshold</Label>
            <Input
              id="low-threshold"
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={settings.lowConfidenceThreshold}
              onChange={(e) => patch({ lowConfidenceThreshold: Number(e.target.value) })}
              className="font-tabular"
            />
          </div>
        </div>
        <p className="text-xs text-muted-foreground flex items-center gap-1.5">
          <Plus className="h-3 w-3 rotate-45" /> Fields at or above the high threshold show green; below the low
          threshold show red; everything between shows amber.
        </p>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// OCR benchmark (CER)
// ---------------------------------------------------------------------------

function CerBenchmarkPanel() {
  const [benchmark, setBenchmark] = useState<CerBenchmarkResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    getCerBenchmark().then((result) => {
      setBenchmark(result);
      setIsLoading(false);
    });
  }, []);

  if (isLoading || !benchmark) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading benchmark…
        </CardContent>
      </Card>
    );
  }

  const scripts: Array<"urdu_nastaliq" | "marathi_devanagari"> = ["urdu_nastaliq", "marathi_devanagari"];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Multi-script OCR benchmark</CardTitle>
        <CardDescription>
          Character Error Rate (CER) per script per engine on the 100-document synthetic sample set —
          Week 9 deliverable. Lower is better; the lowest-CER engine per script is marked Selected.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {scripts.map((script) => {
          const rows = benchmark.entries
            .filter((e) => e.scriptType === script)
            .sort((a, b) => a.cer - b.cer);
          const selected = benchmark.selectedEngine[script];
          return (
            <div key={script} className="space-y-2">
              <h3 className="text-sm font-semibold">{benchmark.scriptLabels[script]}</h3>
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="px-4 py-2 font-medium">Engine</th>
                      <th className="px-4 py-2 font-medium">CER</th>
                      <th className="px-4 py-2 font-medium">Sample size</th>
                      <th className="px-4 py-2 font-medium" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.engine} className="border-b border-border last:border-b-0">
                        <td className="px-4 py-2">{benchmark.engineLabels[row.engine]}</td>
                        <td className="px-4 py-2 font-tabular">{(row.cer * 100).toFixed(1)}%</td>
                        <td className="px-4 py-2 font-tabular text-muted-foreground">{row.sampleSize} docs</td>
                        <td className="px-4 py-2">
                          {row.engine === selected && <Badge variant="success">Selected</Badge>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })}
        <p className="text-xs text-muted-foreground">
          Nastaliq OCR is materially harder than Devanagari across every engine — matches the pod risk
          note. If CER stays high here, narrow the live demo to Marathi/Devanagari and state Urdu as
          calibrated-roadmap.
        </p>
      </CardContent>
    </Card>
  );
}

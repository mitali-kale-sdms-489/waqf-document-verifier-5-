import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useLocation, useNavigate } from "react-router-dom";
import { Eye, EyeOff, Lock, Mail, User } from "lucide-react";
import toast from "react-hot-toast";
import { useAuth } from "@/contexts/AuthContext";
import { loginSchema, registerSchema, type LoginFormValues, type RegisterFormValues } from "@/schemas/auth";
// Matches the seeded accounts in app/seed.py — shown here purely as a
// sign-in hint, not a stand-in for backend auth (see AuthContext.tsx).
const DEMO_CREDENTIALS: { role: string; email: string; password: string }[] = [
  { role: "Supervisor", email: "supervisor@waqf.gov.in", password: "Supervisor@Waqf2025" },
  { role: "User", email: "user@waqf.gov.in", password: "User@Waqf2025" },
];
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const APP_VERSION = "v2.1.0";

function SignInPanel() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [showPassword, setShowPassword] = useState(false);

  const {
    register,
    handleSubmit,
    setValue,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "", rememberMe: false },
  });

  async function onSubmit(values: LoginFormValues) {
    try {
      const user = await login(values.email, values.password);
      toast.success(`Welcome back, ${user.full_name}`);
      const redirectTo =
        (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ??
        "/dashboard";
      navigate(redirectTo, { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Sign-in failed.";
      setError("password", { message });
      toast.error(message);
    }
  }

  function autofill(email: string, password: string) {
    setValue("email", email, { shouldValidate: true });
    setValue("password", password, { shouldValidate: true });
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <div className="relative">
            <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="you@waqf.gov.in"
              className="pl-9"
              {...register("email")}
            />
          </div>
          {errors.email && <p className="text-xs text-rust">{errors.email.message}</p>}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              placeholder="••••••••"
              className="pl-9 pr-9"
              {...register("password")}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          {errors.password && <p className="text-xs text-rust">{errors.password.message}</p>}
        </div>

        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer">
            <Checkbox onCheckedChange={(checked) => setValue("rememberMe", checked === true)} />
            Remember me
          </label>
          <button
            type="button"
            onClick={() => toast("Contact your Waqf board administrator to reset access.")}
            className="text-sm text-primary hover:underline underline-offset-4"
          >
            Forgot password?
          </button>
        </div>

        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? "Signing in…" : "Sign In"}
        </Button>
      </form>

      <div className="border-t border-border pt-4 space-y-2">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Demo credentials
        </p>
        <div className="space-y-1.5">
          {DEMO_CREDENTIALS.map((cred) => (
            <div
              key={cred.email}
              className="flex items-center justify-between gap-2 rounded-md bg-muted px-3 py-2 text-xs"
            >
              <div className="font-mono leading-snug">
                <div className="text-foreground">{cred.role}</div>
                <div className="text-muted-foreground">
                  {cred.email} / {cred.password}
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 px-2 text-[11px] shrink-0"
                onClick={() => autofill(cred.email, cred.password)}
              >
                Use
              </Button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function CreateAccountPanel({ onCreated }: { onCreated: () => void }) {
  const { register: registerAccount } = useAuth();
  const navigate = useNavigate();
  const [showPassword, setShowPassword] = useState(false);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { fullName: "", email: "", password: "", confirmPassword: "" },
  });

  async function onSubmit(values: RegisterFormValues) {
    try {
      const user = await registerAccount(values.fullName, values.email, values.password);
      toast.success(`Account created — welcome, ${user.full_name}`);
      onCreated();
      navigate("/dashboard", { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not create account.";
      setError("email", { message });
      toast.error(message);
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <div className="space-y-1.5">
          <Label htmlFor="fullName">Full name</Label>
          <div className="relative">
            <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              id="fullName"
              type="text"
              autoComplete="name"
              placeholder="Your full name"
              className="pl-9"
              {...register("fullName")}
            />
          </div>
          {errors.fullName && <p className="text-xs text-rust">{errors.fullName.message}</p>}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="registerEmail">Email</Label>
          <div className="relative">
            <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              id="registerEmail"
              type="email"
              autoComplete="email"
              placeholder="you@waqf.gov.in"
              className="pl-9"
              {...register("email")}
            />
          </div>
          {errors.email && <p className="text-xs text-rust">{errors.email.message}</p>}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="registerPassword">Password</Label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              id="registerPassword"
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              placeholder="••••••••"
              className="pl-9 pr-9"
              {...register("password")}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          {errors.password ? (
            <p className="text-xs text-rust">{errors.password.message}</p>
          ) : (
            <p className="text-xs text-muted-foreground">
              At least 8 characters, with an uppercase letter and a number.
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="confirmPassword">Confirm password</Label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              id="confirmPassword"
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              placeholder="••••••••"
              className="pl-9"
              {...register("confirmPassword")}
            />
          </div>
          {errors.confirmPassword && (
            <p className="text-xs text-rust">{errors.confirmPassword.message}</p>
          )}
        </div>

        <p className="text-xs text-muted-foreground">
          New accounts are created with standard <span className="font-medium">User</span> access
          (document upload only). Contact your administrator for Supervisor access.
        </p>

        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </div>
  );
}

export function Login() {
  const [tab, setTab] = useState<"signin" | "signup">("signin");

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4 bg-primary relative overflow-hidden"
      style={{
        backgroundImage:
          "repeating-linear-gradient(0deg, rgba(237,239,234,0.05) 0px, rgba(237,239,234,0.05) 1px, transparent 1px, transparent 32px)",
      }}
    >
      {/* Subtle ledger-paper vignette */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background: "radial-gradient(ellipse at center, transparent 40%, rgba(0,0,0,0.25) 100%)",
        }}
        aria-hidden
      />

      <div className="relative w-full max-w-sm">
        <div className="bg-card text-card-foreground rounded-lg shadow-2xl border border-brass/20 p-6 space-y-4">
          <div className="flex flex-col items-center gap-1 text-center">
            <h1 className="font-display text-base tracking-wide">📜 WAQF DOCUMENT VERIFIER</h1>
            <p className="text-xs text-muted-foreground">
              {tab === "signin"
                ? "Sign in to review Waqf record submissions"
                : "Create an account to submit Waqf record scans"}
            </p>
          </div>

          <Tabs value={tab} onValueChange={(v) => setTab(v as "signin" | "signup")}>
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="signin">Sign In</TabsTrigger>
              <TabsTrigger value="signup">Create account</TabsTrigger>
            </TabsList>
            <TabsContent value="signin">
              <SignInPanel />
            </TabsContent>
            <TabsContent value="signup">
              <CreateAccountPanel onCreated={() => setTab("signin")} />
            </TabsContent>
          </Tabs>
        </div>

        <p className="text-center text-xs text-primary-foreground/50 mt-4 font-tabular">
          {APP_VERSION}
        </p>
      </div>
    </div>
  );
}

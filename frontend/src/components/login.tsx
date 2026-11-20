"use client";
import { useState } from "react";
import { Sparkles } from "lucide-react";
import { AUTH_MODE, signIn, signInWithGoogle, resetPassword, resendVerification, signOut } from "@/lib/auth";
import { Button, Field, Input } from "./ui";
import { toast } from "./ui/toast";

export function LoginScreen({ verify }: { verify?: boolean }) {
  const [email, setEmail] = useState(AUTH_MODE === "dev" ? "admin@spark.example" : "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<void>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) toast.ok(ok); } catch (e) { toast.error("Sign-in failed", e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm rounded-lg border border-border bg-panel p-6">
        <div className="mb-5 flex items-center gap-2"><Sparkles className="size-5 text-accent" /><h1 className="text-lg font-semibold">Authentic Spark</h1></div>
        {verify ? (
          <div className="space-y-3 text-sm">
            <p>Please verify your email address to continue.</p>
            <Button onClick={() => run(resendVerification, "Verification email sent")} loading={busy}>Resend verification</Button>
            <Button variant="ghost" onClick={() => signOut()}>Use another account</Button>
          </div>
        ) : (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run(() => signIn(email, password)); }}>
            <Field label="Email"><Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></Field>
            {AUTH_MODE !== "dev" && <Field label="Password"><Input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></Field>}
            <Button type="submit" className="w-full" loading={busy}>Sign in</Button>
            {AUTH_MODE === "dev" ? (
              <p className="text-xs text-muted">Local development sign-in (backend AUTH_MODE=dev). Seeded users: admin@, ops@, email@, finance@, compliance@, am@spark.example.</p>
            ) : (
              <>
                <Button type="button" variant="secondary" className="w-full" onClick={() => run(signInWithGoogle)}>Continue with Google</Button>
                <button type="button" className="text-xs text-accent hover:underline" onClick={() => run(() => resetPassword(email), "Password reset email sent")}>Forgot password?</button>
              </>
            )}
          </form>
        )}
      </div>
    </div>
  );
}

"use client";

import { LockIcon, MailIcon, UserIcon, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { homeFor, type Role } from "@/components/role-gate";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldError, FieldGroup, FieldLabel, FieldSeparator } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { api, forgetToken } from "@/lib/api";
import { signIn, signUp } from "@/lib/auth-client";

type Me = { role: Role; has_service: boolean };

/** An input with a quiet icon at its left edge. */
function Iconed({ icon: Icon, children }: { icon: LucideIcon; children: React.ReactNode }) {
  return (
    <div className="relative">
      <Icon aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
      {children}
    </div>
  );
}

/** Google's "G", in its own colours, as the provider asks. */
function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className="size-4">
      <path fill="#4285F4" d="M23.52 12.27c0-.85-.08-1.67-.22-2.45H12v4.64h6.47a5.53 5.53 0 0 1-2.4 3.63v3h3.88c2.27-2.09 3.57-5.17 3.57-8.82Z" />
      <path fill="#34A853" d="M12 24c3.24 0 5.96-1.07 7.95-2.91l-3.88-3c-1.08.72-2.45 1.15-4.07 1.15-3.13 0-5.78-2.11-6.73-4.96H1.26v3.1A12 12 0 0 0 12 24Z" />
      <path fill="#FBBC05" d="M5.27 14.28a7.2 7.2 0 0 1 0-4.56v-3.1H1.26a12 12 0 0 0 0 10.76l4.01-3.1Z" />
      <path fill="#EA4335" d="M12 4.77c1.76 0 3.34.61 4.59 1.8l3.44-3.44A11.5 11.5 0 0 0 12 0 12 12 0 0 0 1.26 6.62l4.01 3.1C6.22 6.88 8.87 4.77 12 4.77Z" />
    </svg>
  );
}

export function AuthForm({ mode }: { mode: "sign-in" | "sign-up" }) {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function afterAuth() {
    forgetToken();
    const me = await api<Me>("/me");
    if (me.role === "customer" && !me.has_service) router.replace("/onboarding");
    else router.replace(next && next.startsWith("/") ? next : homeFor(me.role));
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const email = String(form.get("email"));
    const password = String(form.get("password"));
    setBusy(true);
    setError(null);
    const { error } =
      mode === "sign-in"
        ? await signIn.email({ email, password })
        : await signUp.email({ email, password, name: String(form.get("name")) });
    if (error) {
      setError(
        mode === "sign-in"
          ? "That email and password do not match."
          : (error.message ?? "We could not create your account."),
      );
      setBusy(false);
      return;
    }
    await afterAuth().catch(() => setError("Signed in, but we could not load your account. Try again."));
    setBusy(false);
  }

  const google = () => signIn.social({ provider: "google", callbackURL: mode === "sign-up" ? "/onboarding" : (next ?? "/app") });

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle className="text-xl">{mode === "sign-in" ? "Welcome back" : "Create your account"}</CardTitle>
        <CardDescription>
          {mode === "sign-in" ? "Sign in to manage your service." : "It takes a minute. No card needed yet."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit}>
          <FieldGroup>
            <Button type="button" variant="outline" size="lg" onClick={google}>
              <GoogleMark /> Continue with Google
            </Button>
            <FieldSeparator>or with email</FieldSeparator>
            {mode === "sign-up" && (
              <Field>
                <FieldLabel htmlFor="name">Full name</FieldLabel>
                <Iconed icon={UserIcon}><Input id="name" name="name" autoComplete="name" required maxLength={120} className="pl-9" /></Iconed>
              </Field>
            )}
            <Field>
              <FieldLabel htmlFor="email">Email</FieldLabel>
              <Iconed icon={MailIcon}><Input id="email" name="email" type="email" autoComplete="email" required className="pl-9" /></Iconed>
            </Field>
            <Field data-invalid={!!error}>
              <FieldLabel htmlFor="password">Password</FieldLabel>
              <Iconed icon={LockIcon}>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
                  minLength={8}
                  required
                  aria-invalid={!!error}
                  className="pl-9"
                />
              </Iconed>
              <FieldError>{error}</FieldError>
            </Field>
            <Button type="submit" size="lg" disabled={busy}>
              {busy ? "One moment" : mode === "sign-in" ? "Sign in" : "Create account"}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              {mode === "sign-in" ? "New to Lanka Link? " : "Already with us? "}
              <Link className="text-foreground underline underline-offset-4" href={mode === "sign-in" ? "/sign-up" : "/sign-in"}>
                {mode === "sign-in" ? "Create an account" : "Sign in"}
              </Link>
            </p>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  );
}

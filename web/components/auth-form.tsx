"use client";

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

  const social = (provider: "google" | "github") =>
    signIn.social({ provider, callbackURL: mode === "sign-up" ? "/onboarding" : (next ?? "/app") });

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
            <div className="grid grid-cols-2 gap-2">
              <Button type="button" variant="outline" onClick={() => social("google")}>
                Google
              </Button>
              <Button type="button" variant="outline" onClick={() => social("github")}>
                GitHub
              </Button>
            </div>
            <FieldSeparator>or with email</FieldSeparator>
            {mode === "sign-up" && (
              <Field>
                <FieldLabel htmlFor="name">Full name</FieldLabel>
                <Input id="name" name="name" autoComplete="name" required maxLength={120} />
              </Field>
            )}
            <Field>
              <FieldLabel htmlFor="email">Email</FieldLabel>
              <Input id="email" name="email" type="email" autoComplete="email" required />
            </Field>
            <Field data-invalid={!!error}>
              <FieldLabel htmlFor="password">Password</FieldLabel>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
                minLength={8}
                required
                aria-invalid={!!error}
              />
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

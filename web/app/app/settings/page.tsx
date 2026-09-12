"use client";

import { useTheme } from "next-themes";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { forgetToken } from "@/lib/api";
import { authClient, signOut, useSession } from "@/lib/auth-client";

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "si", label: "සිංහල" },
  { value: "ta", label: "தமிழ்" },
];
const THEMES = [
  { value: "system", label: "Match my device" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export default function SettingsPage() {
  const router = useRouter();
  const { data } = useSession();
  const { theme, setTheme } = useTheme();
  const [accounts, setAccounts] = useState<string[]>([]);
  const user = data?.user as { name?: string; email?: string; preferredLanguage?: string } | undefined;

  useEffect(() => {
    void authClient.listAccounts().then(({ data }) => setAccounts((data ?? []).map((a) => a.providerId)));
  }, []);

  async function setLanguage(lang: string) {
    const { error } = await authClient.updateUser({ preferredLanguage: lang } as Record<string, string>);
    if (error) toast.error("We could not save that.");
    else toast.success("Language saved");
  }

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <Card>
        <CardHeader>
          <CardTitle>{user?.name}</CardTitle>
          <CardDescription>{user?.email}</CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel>Language for replies</FieldLabel>
              <Select defaultValue={user?.preferredLanguage ?? "en"} items={LANGUAGES} onValueChange={(v) => setLanguage(String(v))}>
                <SelectTrigger className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LANGUAGES.map((l) => (
                    <SelectItem key={l.value} value={l.value}>
                      {l.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel>Appearance</FieldLabel>
              <Select value={theme ?? "system"} items={THEMES} onValueChange={(v) => setTheme(String(v))}>
                <SelectTrigger className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {THEMES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </FieldGroup>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Sign-in methods</CardTitle>
          <CardDescription>
            {accounts.length
              ? accounts.map((a) => (a === "credential" ? "Email and password" : a[0].toUpperCase() + a.slice(1))).join(", ")
              : "Loading"}
          </CardDescription>
        </CardHeader>
      </Card>
      <Button
        variant="outline"
        onClick={async () => {
          await signOut();
          forgetToken();
          router.replace("/");
        }}
      >
        Sign out
      </Button>
    </div>
  );
}

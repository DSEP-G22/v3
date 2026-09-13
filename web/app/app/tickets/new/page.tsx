"use client";

import { ArrowLeftIcon, CreditCardIcon, HelpCircleIcon, PackageIcon, RouterIcon, WifiIcon, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { NoticeCard, type Notice } from "@/components/notice-card";
import { TicketComposer } from "@/components/ticket-composer";
import { Input } from "@/components/ui/input";
import { ApiError, bearer, useApi } from "@/lib/api";
import { cn } from "@/lib/utils";

const CATEGORIES: { key: string; label: string; icon: LucideIcon; hint: string }[] = [
  { key: "connection", label: "Connection", icon: WifiIcon, hint: "No internet, slow, dropping" },
  { key: "equipment", label: "Router and cables", icon: RouterIcon, hint: "Lights, cables, the device" },
  { key: "billing", label: "Billing", icon: CreditCardIcon, hint: "Bills, charges, payments" },
  { key: "plan", label: "My plan", icon: PackageIcon, hint: "Upgrade, data, contract" },
  { key: "other", label: "Something else", icon: HelpCircleIcon, hint: "Anything else" },
];

export default function NewTicket() {
  const router = useRouter();
  const notices = useApi<{ notices: Notice[] }>("/app/notices");
  const [category, setCategory] = useState("connection");
  const [subject, setSubject] = useState("");
  const [busy, setBusy] = useState(false);

  async function open(form: FormData) {
    setBusy(true);
    form.set("category", category);
    if (subject.trim()) form.set("subject", subject.trim());
    try {
      const t = await bearer();
      const r = await fetch("/api/app/messages", { method: "POST", body: form, headers: t ? { authorization: `Bearer ${t}` } : {} });
      const body = await r.json();
      if (!r.ok) throw new ApiError(r.status, body.detail ?? "We could not open that ticket. Try again.");
      toast.success("Ticket opened. We are on it.");
      router.push(`/app/tickets/${body.ticket.id}`);
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-6">
        <Link href="/app/tickets" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeftIcon className="size-4" /> Support
        </Link>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Open a ticket</h1>
          <p className="text-muted-foreground">Write in English, Sinhala or Tamil. A photo of your router helps us a lot.</p>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">What is it about?</legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {CATEGORIES.map(({ key, label, icon: Icon, hint }) => (
              <button key={key} type="button" aria-pressed={category === key} onClick={() => setCategory(key)}
                      className={cn("flex flex-col items-start gap-2 rounded-2xl border bg-card p-3 text-left transition-all hover:-translate-y-0.5 hover:border-primary/60",
                        category === key && "border-primary bg-primary/5 ring-4 ring-primary/10")}>
                <Icon className={cn("size-5", category === key ? "text-primary" : "text-muted-foreground")} />
                <span className="text-sm font-medium">{label}</span>
                <span className="text-xs text-muted-foreground">{hint}</span>
              </button>
            ))}
          </div>
        </fieldset>

        <div className="space-y-2">
          <label htmlFor="subject" className="text-sm font-medium">Subject <span className="font-normal text-muted-foreground">(optional)</span></label>
          <Input id="subject" value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={120}
                 placeholder="For example: Router light is red since this morning" />
        </div>

        <TicketComposer onSubmit={open} busy={busy} submitLabel="Open ticket"
                        placeholder="Tell us what is happening. When did it start? What have you tried?" />
      </div>

      <aside className="space-y-3">
        <h2 className="text-sm font-medium">Before you write</h2>
        {notices.data?.notices.length ? (
          notices.data.notices.map((n, i) => <NoticeCard key={i} n={n} />)
        ) : (
          <p className="rounded-2xl border border-dashed p-4 text-sm text-muted-foreground">
            Nothing on our side is affecting your service right now.
          </p>
        )}
      </aside>
    </div>
  );
}

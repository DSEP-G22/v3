"use client";

import { CheckIcon, LockIcon, QrCodeIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { FocusLayer, type Origin } from "@/components/fx/focus-layer";
import { Button } from "@/components/ui/button";
import { api, post } from "@/lib/api";
import { cn } from "@/lib/utils";

type Intent = { status: "requires_payment" | "processing" | "succeeded" | "cancelled" };
type Stage = "starting" | "choose" | "processing" | "done" | "error";

// Stub methods only. Nothing here shows or collects card numbers.
const METHODS = [
  { value: "card_4242", label: "Card ending 4242", hint: "Your saved card" },
  { value: "lankaqr", label: "LankaQR", hint: "Scan from your banking app" },
];

/**
 * Pay without leaving the page: a floating window over a gradual blur. `start` creates the
 * payment intent (a balance or one invoice); the window then takes the method, pays, waits
 * for settlement and reports back through onPaid.
 */
export function PayDialog({ open, origin, onClose, start, title, onPaid }: {
  open: boolean;
  origin: Origin | null;
  onClose: () => void;
  start: () => Promise<{ intent_id: string; amount_display: string }>;
  title: string;
  onPaid?: () => void;
}) {
  const [stage, setStage] = useState<Stage>("starting");
  const [intent, setIntent] = useState<{ id: string; amount: string } | null>(null);
  const [method, setMethod] = useState("card_4242");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setStage("starting");
    setIntent(null);
    setError(null);
    start()
      .then((r) => { setIntent({ id: r.intent_id, amount: r.amount_display }); setStage("choose"); })
      .catch((e) => { setError((e as Error).message); setStage("error"); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (stage !== "processing" || !intent) return;
    const t = setInterval(async () => {
      const i = await api<Intent>(`/app/intents/${intent.id}`).catch(() => null);
      if (i?.status === "succeeded") {
        setStage("done");
        onPaid?.();
      } else if (i?.status === "cancelled") {
        setError("The payment was cancelled.");
        setStage("error");
      }
    }, 700);
    return () => clearInterval(t);
  }, [stage, intent, onPaid]);

  async function pay() {
    if (!intent) return;
    setStage("processing");
    try {
      await post(`/app/intents/${intent.id}/pay`, { method });
    } catch (e) {
      setError((e as Error).message);
      setStage("error");
    }
  }

  return (
    <FocusLayer open={open} origin={origin} onClose={onClose} title={title} width={360}
                subtitle={stage === "done" ? undefined : "Choose how you would like to pay."}>
      {stage === "starting" && <div className="h-40 animate-pulse rounded-xl bg-muted" />}

      {stage === "error" && (
        <div className="space-y-3">
          <p className="text-sm text-destructive">{error}</p>
          <Button variant="outline" className="w-full" onClick={onClose}>Close</Button>
        </div>
      )}

      {(stage === "choose" || stage === "processing") && intent && (
        <div className="space-y-4">
          <p className="text-3xl font-semibold tracking-tight tabular-nums">{intent.amount}</p>
          <div className="grid gap-2" role="radiogroup" aria-label="Payment method">
            {METHODS.map((m) => (
              <button key={m.value} type="button" role="radio" aria-checked={method === m.value}
                      disabled={stage === "processing"} onClick={() => setMethod(m.value)}
                      className={cn("flex items-center gap-3 rounded-xl border p-3 text-left transition-all",
                        method === m.value ? "border-primary bg-primary/5 ring-4 ring-primary/10" : "hover:border-primary/50")}>
                <span className={cn("grid size-4 place-items-center rounded-full border", method === m.value && "border-primary bg-primary")}>
                  {method === m.value && <span className="size-1.5 rounded-full bg-primary-foreground" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">{m.label}</span>
                  <span className="block text-xs text-muted-foreground">{m.hint}</span>
                </span>
                {m.value === "lankaqr" && <QrCodeIcon className="size-5 text-muted-foreground" />}
              </button>
            ))}
          </div>
          <Button size="lg" className="h-11 w-full" onClick={pay} disabled={stage === "processing"}>
            {stage === "processing" ? (
              <span className="flex items-center gap-2"><span className="size-4 animate-spin rounded-full border-2 border-primary-foreground/40 border-t-primary-foreground" />Confirming with your bank</span>
            ) : `Pay ${intent.amount}`}
          </Button>
          <p className="flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
            <LockIcon className="size-3" /> Demo payment. No card details are collected.
          </p>
        </div>
      )}

      {stage === "done" && intent && (
        <div className="space-y-4 text-center">
          <span className="mx-auto grid size-16 place-items-center rounded-full bg-success/15 text-success animate-in zoom-in-50 duration-500">
            <CheckIcon className="size-8" />
          </span>
          <div>
            <p className="text-lg font-semibold">Payment received</p>
            <p className="text-sm text-muted-foreground">{intent.amount} paid. If your service was paused, it is coming back now.</p>
          </div>
          <Button className="w-full" onClick={onClose}>Done</Button>
        </div>
      )}
    </FocusLayer>
  );
}

"use client";

import { AngryIcon, FrownIcon, LaughIcon, MehIcon, SmileIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { post } from "@/lib/api";
import { cn } from "@/lib/utils";

const FACES = [
  { value: 1, icon: AngryIcon, label: "Very poor" },
  { value: 2, icon: FrownIcon, label: "Poor" },
  { value: 3, icon: MehIcon, label: "Okay" },
  { value: 4, icon: SmileIcon, label: "Good" },
  { value: 5, icon: LaughIcon, label: "Great" },
];

/** Rate a ticket one to five with an optional comment. Shows the saved rating once given. */
export function TicketFeedback({ ticketId, rating, comment, onSaved }: {
  ticketId: string; rating: number | null; comment: string | null; onSaved?: () => void;
}) {
  const [value, setValue] = useState<number | null>(rating);
  const [text, setText] = useState(comment ?? "");
  const [saved, setSaved] = useState(rating != null);
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!value) return;
    setBusy(true);
    try {
      await post(`/app/tickets/${ticketId}/feedback`, { rating: value, comment: text });
      setSaved(true);
      toast.success("Thank you. Your feedback helps us answer better.");
      onSaved?.();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="fb" className="rounded-2xl border bg-linear-to-br from-primary/5 via-card to-highlight/10 p-5">
      <h2 id="fb" className="font-semibold">{saved ? "Your rating" : "How did we do?"}</h2>
      <div className="mt-3 flex gap-2" role="radiogroup" aria-label="Rating">
        {FACES.map(({ value: v, icon: Icon, label }) => (
          <button key={v} type="button" role="radio" aria-checked={value === v} aria-label={label} disabled={saved}
                  onClick={() => setValue(v)}
                  className={cn("grid size-11 place-items-center rounded-xl border bg-background transition-all hover:-translate-y-0.5 hover:border-primary",
                    value === v && "scale-110 border-primary bg-primary text-primary-foreground shadow-md shadow-primary/30",
                    saved && value !== v && "opacity-40")}>
            <Icon className="size-5" />
          </button>
        ))}
      </div>
      {saved ? (
        text && <p className="mt-3 text-sm text-muted-foreground">&ldquo;{text}&rdquo;</p>
      ) : (
        <div className="mt-3 space-y-2">
          <Textarea rows={2} placeholder="Anything we could have done better? (optional)" value={text}
                    onChange={(e) => setText(e.target.value)} maxLength={1000} />
          <Button size="sm" onClick={save} disabled={!value || busy}>{busy ? "Saving" : "Send feedback"}</Button>
        </div>
      )}
    </section>
  );
}

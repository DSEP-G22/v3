"use client";

import { ImagePlusIcon, MicIcon, SquareIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MAX_VOICE_SECONDS, useRecorder } from "@/lib/use-recorder";

type Pending = { file: File; url: string };

/** Message, photos and a voice note. Hands the caller a FormData with text and files set. */
export function TicketComposer({ onSubmit, placeholder, submitLabel, busy }: {
  onSubmit: (form: FormData) => Promise<boolean>;
  placeholder: string;
  submitLabel: string;
  busy: boolean;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<Pending[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const addFile = useCallback((file: File) => setFiles((f) => [...f, { file, url: URL.createObjectURL(file) }].slice(0, 5)), []);
  const rec = useRecorder(addFile);

  useEffect(() => {
    if (rec.error) toast.error(rec.error);
  }, [rec.error]);

  async function submit() {
    if (!text.trim() && !files.length) return toast.error("Write a few words or attach a photo or voice note.");
    const form = new FormData();
    form.set("text", text.trim());
    files.forEach(({ file }) => form.append("files", file));
    if (await onSubmit(form)) {
      files.forEach(({ url }) => URL.revokeObjectURL(url));
      setText("");
      setFiles([]);
    }
  }

  return (
    <div className="space-y-3 rounded-2xl border bg-card p-3 shadow-sm focus-within:border-primary/50 focus-within:ring-4 focus-within:ring-primary/10">
      <Textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder}
                className="resize-none border-0 bg-transparent shadow-none focus-visible:ring-0" />
      {!!files.length && (
        <div className="flex flex-wrap gap-2">
          {files.map(({ file, url }, i) => (
            <div key={url} className="relative">
              {file.type.startsWith("image/") ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={url} alt={file.name} className="size-16 rounded-lg border object-cover" />
              ) : (
                <audio src={url} controls className="h-10 w-56" />
              )}
              <button type="button" aria-label={`Remove ${file.name}`} onClick={() => setFiles((f) => f.filter((_, j) => j !== i))}
                      className="absolute -top-1.5 -right-1.5 grid size-5 place-items-center rounded-full bg-foreground text-background">
                <XIcon className="size-3" />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <input ref={input} type="file" accept="image/*" multiple hidden
               onChange={(e) => { Array.from(e.target.files ?? []).forEach(addFile); e.target.value = ""; }} />
        <Button type="button" variant="ghost" size="sm" onClick={() => input.current?.click()}>
          <ImagePlusIcon /> Photo
        </Button>
        {rec.recording ? (
          <div className="flex items-center gap-2 text-sm">
            <div aria-hidden className="flex h-6 items-center gap-px">
              {rec.levels.map((l, i) => <span key={i} className="w-0.5 rounded-full bg-primary" style={{ height: `${Math.max(8, l * 100)}%` }} />)}
            </div>
            <span className="tabular-nums text-muted-foreground">0:{String(rec.seconds).padStart(2, "0")} / 1:00</span>
            <Button type="button" variant="ghost" size="sm" onClick={rec.stop} aria-label="Stop recording"><SquareIcon /> Stop</Button>
          </div>
        ) : (
          <Button type="button" variant="ghost" size="sm" onClick={rec.start}><MicIcon /> Voice note</Button>
        )}
        <Button type="button" className="ml-auto" onClick={submit} disabled={busy || rec.recording}>
          {busy ? "Sending" : submitLabel}
        </Button>
      </div>
      <p className="sr-only">Voice notes can be up to {MAX_VOICE_SECONDS} seconds.</p>
    </div>
  );
}

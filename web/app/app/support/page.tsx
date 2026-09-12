"use client";

import { MicIcon, SquareIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  Attachment,
  AttachmentPreview,
  AttachmentRemove,
  Attachments,
} from "@/components/ai-elements/attachments";
import { SentAttachment, type Att } from "@/components/authed-media";
import { Conversation, ConversationContent, ConversationScrollButton } from "@/components/ai-elements/conversation";
import { Message, MessageContent } from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputActionAddAttachments,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuTrigger,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputHeader,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputAttachments,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Suggestion, Suggestions } from "@/components/ai-elements/suggestion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, bearer, post, useApi, useEvents } from "@/lib/api";
import { useSession } from "@/lib/auth-client";
import { MAX_VOICE_SECONDS, useRecorder } from "@/lib/use-recorder";

type Msg = {
  id: string;
  author_kind: "customer" | "assistant" | "agent" | "system";
  body: string;
  body_en?: string | null;
  lang?: string | null;
  case_id?: string | null;
  status: string;
  created_at: string;
  attachments: Att[];
};
type Conv = { conversation: { id: string; open_case_id: string | null } | null; messages: Msg[] };
type Stage = { chip: "reading" | "checking" | "writing" | "held"; expected?: string | null };

const CHIP: Record<Exclude<Stage["chip"], "held">, string> = {
  reading: "Reading your message",
  checking: "Checking your account",
  writing: "Writing a reply",
};
const LANGUAGE: Record<string, string> = { si: "Sinhala", ta: "Tamil", "si-Latn": "Sinhala", "ta-Latn": "Tamil" };
const SUGGESTIONS: Record<string, string[]> = {
  en: ["My internet is not working", "Why is my bill higher this month?", "The light on my router is red"],
  si: ["මගේ අන්තර්ජාලය වැඩ කරන්නේ නැහැ", "මේ මාසේ බිල වැඩි ඇයි?", "රවුටරයේ රතු ලයිට් එකක් තියෙනවා"],
  ta: ["என் இணையம் வேலை செய்யவில்லை", "இந்த மாதம் பில் ஏன் அதிகம்?", "ரவுட்டரில் சிவப்பு விளக்கு எரிகிறது"],
};

function Reply({ m }: { m: Msg }) {
  const [english, setEnglish] = useState(false);
  const translated = m.lang && m.lang !== "en" && m.body_en;
  return (
    <div className="space-y-1">
      <p className="whitespace-pre-line">{english && m.body_en ? m.body_en : m.body}</p>
      {translated && (
        <button type="button" className="text-xs text-muted-foreground underline underline-offset-4"
                onClick={() => setEnglish((v) => !v)}>
          {english ? "Show translation" : "Show original (English)"}
        </button>
      )}
    </div>
  );
}

function PendingFiles() {
  const attachments = usePromptInputAttachments();
  if (!attachments.files.length) return null;
  return (
    <PromptInputHeader>
      <Attachments variant="inline">
        {attachments.files.map((f) => (
          <Attachment key={f.id} data={f} onRemove={() => attachments.remove(f.id)}>
            <AttachmentPreview />
            <AttachmentRemove />
          </Attachment>
        ))}
      </Attachments>
    </PromptInputHeader>
  );
}

function VoiceButton() {
  const attachments = usePromptInputAttachments();
  const onDone = useCallback((file: File) => attachments.add([file]), [attachments]);
  const rec = useRecorder(onDone);
  useEffect(() => {
    if (rec.error) toast.error(rec.error);
  }, [rec.error]);
  if (!rec.recording) {
    return (
      <PromptInputButton onClick={rec.start} aria-label="Record a voice note">
        <MicIcon className="size-4" />
      </PromptInputButton>
    );
  }
  return (
    <div className="flex items-center gap-2 text-sm">
      <div aria-hidden className="flex h-6 items-center gap-px">
        {rec.levels.map((l, i) => (
          <span key={i} className="w-0.5 rounded-full bg-primary" style={{ height: `${Math.max(8, l * 100)}%` }} />
        ))}
      </div>
      <span className="tabular-nums text-muted-foreground">
        0:{String(rec.seconds).padStart(2, "0")} / 1:00
      </span>
      <PromptInputButton onClick={rec.stop} aria-label="Stop recording">
        <SquareIcon className="size-4" />
      </PromptInputButton>
    </div>
  );
}

export default function Support() {
  const { data, loading, reload } = useApi<Conv>("/app/conversation");
  const { data: session } = useSession();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [stage, setStage] = useState<Stage | null>(null);
  const [heard, setHeard] = useState<string | null>(null);
  const [language, setLanguage] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const lang = (session?.user as { preferredLanguage?: string } | undefined)?.preferredLanguage ?? "en";
  const openCase = data?.conversation?.open_case_id ?? messages.findLast((m) => m.case_id)?.case_id ?? null;

  useEffect(() => {
    if (data) setMessages(data.messages);
  }, [data]);

  useEvents((kind, payload) => {
    const p = payload as Record<string, unknown>;
    if (kind === "message") {
      const m = p.message as Msg;
      setMessages((ms) => (ms.some((x) => x.id === m.id) ? ms : [...ms, m]));
      if (m.author_kind !== "customer") {
        setStage(null);
        setHeard(null);
      }
    } else if (kind === "stage") setStage(p as unknown as Stage);
    else if (kind === "heard") setHeard(String(p.text));
    else if (kind === "language") setLanguage(String(p.language));
  });

  async function send(msg: PromptInputMessage) {
    const text = msg.text.trim();
    if (!text && !msg.files.length) return;
    setSending(true);
    const form = new FormData();
    form.set("text", text);
    for (const f of msg.files) {
      const blob = await (await fetch(f.url)).blob();
      form.append("files", new File([blob], f.filename ?? "attachment", { type: f.mediaType }));
    }
    const optimistic: Msg = {
      id: `local-${Date.now()}`, author_kind: "customer", body: text, status: "sending",
      created_at: new Date().toISOString(), attachments: [],
    };
    setMessages((ms) => [...ms, optimistic]);
    try {
      const t = await bearer();
      const r = await fetch("/api/app/messages", {
        method: "POST", body: form, headers: t ? { authorization: `Bearer ${t}` } : {},
      });
      const body = await r.json();
      if (!r.ok) throw new ApiError(r.status, body.detail ?? "We could not send that. Try again.");
      setMessages((ms) => {
        const rest = ms.filter((m) => m.id !== optimistic.id);
        return [...rest, body.message, ...(body.reply ? [body.reply] : [])];
      });
      if (!body.reply) setStage({ chip: "reading" });
    } catch (e) {
      setMessages((ms) => ms.filter((m) => m.id !== optimistic.id));
      toast.error((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  async function solved() {
    if (!openCase) return;
    await post(`/app/cases/${openCase}/solved`).catch(() => null);
    toast.success("Glad that is sorted.");
    setStage(null);
    void reload();
  }

  const rows = useMemo(() => {
    let lastCase: string | null | undefined;
    return messages.map((m) => {
      const divider = m.case_id && m.case_id !== lastCase ? m.case_id : null;
      if (m.case_id) lastCase = m.case_id;
      return { m, divider };
    });
  }, [messages]);

  if (loading) return <Skeleton className="h-[70svh]" />;

  return (
    <div className="flex h-[calc(100svh-9rem)] flex-col">
      <div className="flex items-center justify-between gap-4 pb-3">
        <h1 className="text-2xl font-semibold tracking-tight">Support</h1>
        <div className="flex items-center gap-2">
          {language && LANGUAGE[language] && <Badge variant="secondary">{LANGUAGE[language]}</Badge>}
          {openCase && (
            <Button size="sm" variant="outline" onClick={solved}>
              Solved
            </Button>
          )}
        </div>
      </div>

      <Conversation className="flex-1 rounded-xl border">
        <ConversationContent>
          {!rows.length && (
            <p className="py-10 text-center text-muted-foreground">
              Tell us what is happening. You can add a photo of your router or leave a voice note.
            </p>
          )}
          {rows.map(({ m, divider }) => (
            <div key={m.id} className="space-y-3">
              {divider && (
                <div className="flex items-center gap-3 text-xs text-muted-foreground" role="separator">
                  <span className="h-px flex-1 bg-border" />
                  Case {divider}
                  <span className="h-px flex-1 bg-border" />
                </div>
              )}
              <Message from={m.author_kind === "customer" ? "user" : "assistant"}>
                <MessageContent>
                  {m.author_kind === "customer" ? <p className="whitespace-pre-line">{m.body}</p> : <Reply m={m} />}
                  {m.attachments?.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {m.attachments.map((a) => (
                        <SentAttachment key={a.id} att={a} />
                      ))}
                    </div>
                  )}
                </MessageContent>
              </Message>
            </div>
          ))}
          {heard && (
            <p className="text-sm text-muted-foreground">
              We heard: <span className="text-foreground">&ldquo;{heard}&rdquo;</span>. If that is not right, just type it.
            </p>
          )}
          {stage && stage.chip !== "held" && (
            <span data-testid="stage-chip"><Shimmer className="text-sm">{CHIP[stage.chip]}</Shimmer></span>
          )}
          {stage?.chip === "held" && (
            <div role="status" className="rounded-lg border bg-muted/50 p-3 text-sm">
              One of our team is checking your answer.
              {stage.expected ? ` You will hear from us by ${stage.expected}.` : ""} You can keep writing in the meantime.
            </div>
          )}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      {!openCase && !sending && (
        <Suggestions className="pt-3">
          {(SUGGESTIONS[lang] ?? SUGGESTIONS.en).map((s) => (
            <Suggestion key={s} suggestion={s} onClick={(v) => send({ text: v, files: [] })} />
          ))}
        </Suggestions>
      )}

      <PromptInput className="mt-3" accept="image/*" multiple maxFiles={5} maxFileSize={10 * 1024 * 1024}
                   onError={(e) => toast.error(e.message)} onSubmit={send}>
        <PendingFiles />
        <PromptInputBody>
          <PromptInputTextarea placeholder="Write in English, Sinhala or Tamil" />
        </PromptInputBody>
        <PromptInputFooter>
          <PromptInputTools>
            <PromptInputActionMenu>
              <PromptInputActionMenuTrigger aria-label="Add a photo" />
              <PromptInputActionMenuContent>
                <PromptInputActionAddAttachments label="Add a photo" />
              </PromptInputActionMenuContent>
            </PromptInputActionMenu>
            <VoiceButton />
          </PromptInputTools>
          <PromptInputSubmit status={sending ? "submitted" : undefined} disabled={sending} />
        </PromptInputFooter>
      </PromptInput>
      <p className="sr-only">Voice notes can be up to {MAX_VOICE_SECONDS} seconds.</p>
    </div>
  );
}

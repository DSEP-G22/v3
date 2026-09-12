"use client";

import { useEffect, useState } from "react";

import {
  AudioPlayer,
  AudioPlayerControlBar,
  AudioPlayerElement,
  AudioPlayerPlayButton,
  AudioPlayerTimeDisplay,
  AudioPlayerTimeRange,
} from "@/components/ai-elements/audio-player";
import { Skeleton } from "@/components/ui/skeleton";
import { bearer } from "@/lib/api";

export type Att = { id: string; kind: "image" | "audio"; mime: string };

/** Attachments sit behind the Bearer token, so they are fetched as blobs, not plain URLs. */
export function useBlobUrl(path: string) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let made: string | null = null;
    let live = true;
    void (async () => {
      const t = await bearer();
      const r = await fetch(`/api${path}`, { headers: t ? { authorization: `Bearer ${t}` } : {} });
      if (r.ok && live) {
        made = URL.createObjectURL(await r.blob());
        setUrl(made);
      }
    })();
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [path]);
  return url;
}

export function SentAttachment({ att, alt = "Photo you sent" }: { att: Att; alt?: string }) {
  const url = useBlobUrl(`/app/attachments/${att.id}`);
  if (!url) return <Skeleton className={att.kind === "image" ? "size-32" : "h-9 w-56"} />;
  if (att.kind === "image") {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={url} alt={alt} className="max-h-56 rounded-lg border" />;
  }
  return (
    <AudioPlayer>
      <AudioPlayerElement src={url} />
      <AudioPlayerControlBar>
        <AudioPlayerPlayButton />
        <AudioPlayerTimeRange />
        <AudioPlayerTimeDisplay />
      </AudioPlayerControlBar>
    </AudioPlayer>
  );
}

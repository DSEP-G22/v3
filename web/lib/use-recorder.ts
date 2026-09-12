"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export const MAX_VOICE_SECONDS = 60;

/** Voice notes with MediaRecorder: 60 s cap, a live level for the waveform, a File when done. */
export function useRecorder(onDone: (file: File) => void) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [levels, setLevels] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const stop = useRef<() => void>(() => {});

  const start = useCallback(async () => {
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("We could not use your microphone. Check your browser's permission.");
      return;
    }
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m));
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks: Blob[] = [];
    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Uint8Array(analyser.frequencyBinCount);
    const began = Date.now();

    const tick = setInterval(() => {
      analyser.getByteTimeDomainData(buf);
      const peak = buf.reduce((m, v) => Math.max(m, Math.abs(v - 128)), 0) / 128;
      setLevels((l) => [...l.slice(-47), peak]);
      const s = (Date.now() - began) / 1000;
      setSeconds(Math.floor(s));
      if (s >= MAX_VOICE_SECONDS) stop.current();
    }, 100);

    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      clearInterval(tick);
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close();
      setRecording(false);
      const type = rec.mimeType || "audio/webm";
      const ext = type.includes("mp4") ? "m4a" : "webm";
      if (chunks.length) onDone(new File(chunks, `voice-note.${ext}`, { type }));
    };
    stop.current = () => rec.state !== "inactive" && rec.stop();
    setLevels([]);
    setSeconds(0);
    setRecording(true);
    rec.start(250);
  }, [onDone]);

  useEffect(() => () => stop.current(), []);

  return { recording, seconds, levels, error, start, stop: () => stop.current() };
}

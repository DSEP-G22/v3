"use client";

import { CheckIcon, LocateFixedIcon, MapPinIcon, PhoneIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Brand } from "@/components/brand";
import { RoleGate } from "@/components/role-gate";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { post, useApi } from "@/lib/api";
import type { Plan } from "@/lib/server";
import { cn } from "@/lib/utils";

type Area = { district: string; city: string; technologies: string[] };
const STEPS = ["Plan", "Location", "Installation"] as const;
const SLOTS = [{ value: "morning", label: "Morning", hint: "8 am to 12 noon" },
  { value: "afternoon", label: "Afternoon", hint: "12 noon to 4 pm" }, { value: "evening", label: "Evening", hint: "4 pm to 7 pm" }];
const iso = (d: Date) => d.toISOString().slice(0, 10);

/** New customers: choose a plan, say where the line goes, pick an installation visit, then pay. */
export default function Onboarding() {
  const router = useRouter();
  const plans = useApi<{ plans: Plan[] }>("/public/plans");
  const coverage = useApi<{ areas: Area[] }>("/public/coverage");
  const [step, setStep] = useState(0);
  const [planCode, setPlanCode] = useState("");
  const [district, setDistrict] = useState("");
  const [city, setCity] = useState("");
  const [house, setHouse] = useState("");
  const [street, setStreet] = useState("");
  const [landmark, setLandmark] = useState("");
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState<{ lat: number; lng: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const [date, setDate] = useState("");
  const [slot, setSlot] = useState("morning");
  const [busy, setBusy] = useState(false);

  const plan = plans.data?.plans.find((p) => p.code === planCode);
  const areas = useMemo(() => (coverage.data?.areas ?? []).filter((a) => !plan || a.technologies.includes(plan.technology)), [coverage.data, plan]);
  const districts = [...new Set(areas.map((a) => a.district))].sort();
  const towns = areas.filter((a) => a.district === district);
  const tomorrow = new Date(Date.now() + 86_400_000);
  const address = [house.trim(), street.trim()].filter(Boolean).join(", ");
  const ready = [!!planCode, !!city && !!street.trim() && phone.replace(/\D/g, "").length >= 9, !!date];

  function locate() {
    if (!("geolocation" in navigator)) return toast.error("This browser cannot share a location.");
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (p) => { setPin({ lat: +p.coords.latitude.toFixed(5), lng: +p.coords.longitude.toFixed(5) }); setLocating(false); },
      () => { toast.error("We could not read your location. Fill in the address instead."); setLocating(false); },
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  }

  async function order() {
    setBusy(true);
    try {
      const o = await post<{ intent_id: string }>("/app/orders", {
        kind: "new_service", plan_code: planCode, city, address_line: address, landmark: landmark.trim(),
        phone: phone.trim(), lat: pin?.lat ?? null, lng: pin?.lng ?? null, install_date: date, install_slot: slot,
      });
      router.push(`/checkout/${o.intent_id}`);
    } catch (e) {
      toast.error((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <RoleGate roles={["customer"]}>
      <main className="flex min-h-svh flex-col items-center gap-8 px-4 py-10">
        <Brand />
        <ol className="flex w-full max-w-xl items-center gap-2 text-sm" aria-label="Steps">
          {STEPS.map((s, i) => (
            <li key={s} className="flex flex-1 items-center gap-2">
              <span className={cn("grid size-7 shrink-0 place-items-center rounded-full border text-xs font-medium transition-colors",
                i < step ? "border-primary bg-primary text-primary-foreground" : i === step ? "border-primary text-primary" : "text-muted-foreground")}>
                {i < step ? <CheckIcon className="size-3.5" /> : i + 1}
              </span>
              <span className={cn("hidden sm:inline", i === step ? "font-medium" : "text-muted-foreground")}>{s}</span>
              {i < STEPS.length - 1 && <span className={cn("h-px flex-1", i < step ? "bg-primary" : "bg-border")} />}
            </li>
          ))}
        </ol>

        <section className="surface-3d w-full max-w-xl rounded-3xl p-6">
          <h1 className="text-xl font-semibold tracking-tight">
            {["Choose a plan", "Where should we connect you?", "When should we come?"][step]}
          </h1>
          <p className="mt-1 mb-6 text-sm text-muted-foreground">
            {["You can change it later from your account.", "Our installer uses this to find you and run the line.",
              "Pick a day and a window. We confirm by phone the day before."][step]}
          </p>

          {step === 0 && (plans.loading ? <Skeleton className="h-60" /> : (
            <RadioGroup value={planCode} onValueChange={(v) => { setPlanCode(String(v)); setDistrict(""); setCity(""); }}>
              {plans.data?.plans.map((p) => (
                <FieldLabel key={p.code} htmlFor={p.code} className="w-full rounded-xl border p-3">
                  <RadioGroupItem id={p.code} value={p.code} />
                  <span className="flex flex-1 justify-between gap-4">
                    <span>
                      <span className="block font-medium">{p.name}</span>
                      <span className="block text-sm font-normal text-muted-foreground">
                        Up to {p.speed_display}, {p.data_cap_display === "Unlimited" ? "unlimited data" : p.data_cap_display}
                      </span>
                    </span>
                    <span className="shrink-0 text-sm">{p.price_display}</span>
                  </span>
                </FieldLabel>
              ))}
            </RadioGroup>
          ))}

          {step === 1 && (
            <FieldGroup>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field>
                  <FieldLabel>District</FieldLabel>
                  <Select value={district} onValueChange={(v) => { setDistrict(String(v ?? "")); setCity(""); }}
                          items={districts.map((d) => ({ value: d, label: d }))}>
                    <SelectTrigger className="w-full"><SelectValue placeholder="Select a district" /></SelectTrigger>
                    <SelectContent>{districts.map((d) => <SelectItem key={d} value={d}>{d}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
                <Field>
                  <FieldLabel>Town</FieldLabel>
                  <Select value={city} onValueChange={(v) => setCity(String(v ?? ""))} disabled={!district}
                          items={towns.map((a) => ({ value: a.city, label: a.city }))}>
                    <SelectTrigger className="w-full"><SelectValue placeholder={district ? "Select your town" : "District first"} /></SelectTrigger>
                    <SelectContent>{towns.map((a) => <SelectItem key={a.city} value={a.city}>{a.city}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
              </div>
              {city && (
                <p className="flex items-center gap-2 rounded-xl border border-success/30 bg-success/10 px-3 py-2 text-sm text-success">
                  <CheckIcon className="size-4" /> {plan?.name} is available in {city}.
                </p>
              )}
              <div className="grid gap-4 sm:grid-cols-[8rem_1fr]">
                <Field>
                  <FieldLabel htmlFor="house">House or unit</FieldLabel>
                  <Input id="house" value={house} maxLength={30} onChange={(e) => setHouse(e.target.value)} placeholder="No. 12" />
                </Field>
                <Field>
                  <FieldLabel htmlFor="street">Street</FieldLabel>
                  <Input id="street" value={street} maxLength={120} onChange={(e) => setStreet(e.target.value)} placeholder="Temple Lane" autoComplete="address-line1" />
                </Field>
              </div>
              <Field>
                <FieldLabel htmlFor="landmark">Nearest landmark</FieldLabel>
                <div className="relative">
                  <MapPinIcon aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input id="landmark" className="pl-9" value={landmark} maxLength={120} onChange={(e) => setLandmark(e.target.value)} placeholder="Opposite the temple, blue gate" />
                </div>
              </Field>
              <Field>
                <FieldLabel htmlFor="phone">Phone for the installer</FieldLabel>
                <div className="relative">
                  <PhoneIcon aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input id="phone" className="pl-9" type="tel" inputMode="tel" value={phone} maxLength={20}
                         onChange={(e) => setPhone(e.target.value.replace(/[^0-9+ ]/g, ""))} placeholder="077 123 4567" autoComplete="tel" />
                </div>
              </Field>
              <Field>
                <FieldLabel>Exact spot (optional)</FieldLabel>
                <div className="flex flex-wrap items-center gap-3">
                  <Button type="button" variant="outline" size="sm" onClick={locate} disabled={locating}>
                    <LocateFixedIcon /> {locating ? "Finding you" : pin ? "Update the pin" : "Use my current location"}
                  </Button>
                  {pin && (
                    <a className="text-sm text-muted-foreground underline underline-offset-4" target="_blank" rel="noreferrer"
                       href={`https://www.openstreetmap.org/?mlat=${pin.lat}&mlon=${pin.lng}#map=18/${pin.lat}/${pin.lng}`}>
                      {pin.lat}, {pin.lng}
                    </a>
                  )}
                </div>
                <FieldDescription>Only used to guide the installer to your door.</FieldDescription>
              </Field>
            </FieldGroup>
          )}

          {step === 2 && (
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="date">Installation day</FieldLabel>
                <Input id="date" type="date" value={date} min={iso(tomorrow)} max={iso(new Date(Date.now() + 30 * 86_400_000))}
                       onChange={(e) => setDate(e.target.value)} />
              </Field>
              <Field>
                <FieldLabel>Time window</FieldLabel>
                <RadioGroup value={slot} onValueChange={(v) => setSlot(String(v))} className="grid gap-2 sm:grid-cols-3">
                  {SLOTS.map((s) => (
                    <FieldLabel key={s.value} htmlFor={`slot-${s.value}`} className="rounded-xl border p-3">
                      <RadioGroupItem id={`slot-${s.value}`} value={s.value} />
                      <span><span className="block font-medium">{s.label}</span><span className="block text-xs font-normal text-muted-foreground">{s.hint}</span></span>
                    </FieldLabel>
                  ))}
                </RadioGroup>
              </Field>
              <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1.5 rounded-xl border p-4 text-sm">
                <dt className="text-muted-foreground">Plan</dt><dd>{plan?.name}, {plan?.price_display} a month</dd>
                <dt className="text-muted-foreground">Address</dt><dd>{address}, {city}, {district}</dd>
                {landmark.trim() && <><dt className="text-muted-foreground">Landmark</dt><dd>{landmark}</dd></>}
                <dt className="text-muted-foreground">Phone</dt><dd>{phone}</dd>
              </dl>
            </FieldGroup>
          )}

          <div className="mt-6 flex justify-between gap-2">
            {step > 0 ? <Button variant="ghost" onClick={() => setStep(step - 1)}>Back</Button> : <span />}
            {step < 2 ? (
              <Button disabled={!ready[step]} onClick={() => setStep(step + 1)}>Continue</Button>
            ) : (
              <Button disabled={!ready[2] || busy} onClick={order}>{busy ? "One moment" : "Continue to payment"}</Button>
            )}
          </div>
        </section>
      </main>
    </RoleGate>
  );
}

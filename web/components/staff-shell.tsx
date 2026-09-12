"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Brand } from "@/components/brand";
import { roleOf, type Role } from "@/components/role-gate";
import { Button } from "@/components/ui/button";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { api, forgetToken } from "@/lib/api";
import { signOut, useSession } from "@/lib/auth-client";

type NavItem = { href: string; label: string };
const GROUPS: { label: string; roles: Role[]; items: NavItem[] }[] = [
  { label: "Console", roles: ["agent", "lead", "admin"], items: [{ href: "/console", label: "Inbox" }] },
  {
    label: "Admin", roles: ["admin"], items: [
      { href: "/admin", label: "Overview" },
      { href: "/admin/autoreply", label: "Auto reply" },
      { href: "/admin/models", label: "Models" },
      { href: "/admin/grounding", label: "Grounding plan" },
      { href: "/admin/traces", label: "Traces" },
      { href: "/admin/users", label: "Users and roles" },
    ],
  },
  {
    label: "Simulation", roles: ["operator", "admin"], items: [
      { href: "/sim", label: "Network" },
      { href: "/sim/scenarios", label: "Scenarios" },
      { href: "/sim/customers", label: "Customers" },
      { href: "/sim/lab", label: "Test lab" },
      { href: "/sim/events", label: "Event log" },
    ],
  },
];

/** Cmd/Ctrl+K: jump to a case by reference or summary. */
function JumpToCase() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ id: string; summary: string | null; customer: string }[]>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(async () => {
      const r = await api<{ cases: typeof hits }>(`/console/cases?tab=all&q=${encodeURIComponent(q)}`).catch(() => null);
      setHits(r?.cases.slice(0, 8) ?? []);
    }, 150);
    return () => clearTimeout(t);
  }, [q, open]);

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Case reference or what it is about" value={q} onValueChange={setQ} />
      <CommandList>
        <CommandEmpty>No case found.</CommandEmpty>
        <CommandGroup heading="Cases">
          {hits.map((h) => (
            <CommandItem key={h.id} value={`${h.id} ${h.summary ?? ""}`}
                         onSelect={() => { setOpen(false); router.push(`/console/cases/${h.id}`); }}>
              <span className="font-medium">{h.id}</span>
              <span className="truncate text-muted-foreground">{h.customer}, {h.summary}</span>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}

export function StaffShell({ children, bar }: { children: ReactNode; bar?: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { data } = useSession();
  const role = roleOf(data?.user);

  return (
    <SidebarProvider>
      <Sidebar>
        <SidebarHeader className="px-4 py-3">
          <Brand href={role === "operator" ? "/sim" : role === "admin" ? "/admin" : "/console"} />
        </SidebarHeader>
        <SidebarContent>
          {GROUPS.filter((g) => g.roles.includes(role)).map((g) => (
            <SidebarGroup key={g.label}>
              <SidebarGroupLabel>{g.label}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {g.items.map((item) => {
                    const root = ["/console", "/admin", "/sim"].includes(item.href);
                    const active = root ? path === item.href || (item.href === "/console" && path.startsWith("/console/"))
                      : path.startsWith(item.href);
                    return (
                      <SidebarMenuItem key={item.href}>
                        <SidebarMenuButton isActive={active} render={<Link href={item.href} />}>
                          {item.label}
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    );
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
        </SidebarContent>
        <SidebarFooter className="gap-1 px-4 pb-4 text-sm">
          <span className="truncate">{data?.user.name}</span>
          <span className="text-xs capitalize text-muted-foreground">{role}</span>
          <Button variant="ghost" size="sm" className="justify-start px-0" onClick={async () => {
            await signOut();
            forgetToken();
            router.replace("/sign-in");
          }}>
            Sign out
          </Button>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset className="text-sm">
        <header className="sticky top-0 z-10 flex h-12 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur">
          <SidebarTrigger />
          {bar}
          <span className="ml-auto hidden text-xs text-muted-foreground sm:inline">Ctrl K to find a case</span>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-6">{children}</main>
      </SidebarInset>
      {role !== "operator" && <JumpToCase />}
    </SidebarProvider>
  );
}

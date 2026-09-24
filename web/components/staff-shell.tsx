"use client";

import {
  ActivityIcon,
  BotIcon,
  CpuIcon,
  FlaskConicalIcon,
  GlobeIcon,
  InboxIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  MapIcon,
  NetworkIcon,
  ScrollTextIcon,
  SirenIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { LOGO_RATIO, LogoIcon, LogoMark } from "@/components/logo";
import { roleOf, signOutTo, type Role } from "@/components/role-gate";
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
  useSidebar,
} from "@/components/ui/sidebar";
import { api, prefetch } from "@/lib/api";
import { useSession } from "@/lib/auth-client";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: LucideIcon };
const GROUPS: { label: string; roles: Role[]; items: NavItem[] }[] = [
  { label: "Console", roles: ["agent", "lead", "admin"], items: [{ href: "/console", label: "Inbox", icon: InboxIcon }] },
  {
    label: "Admin", roles: ["admin"], items: [
      { href: "/admin", label: "Overview", icon: LayoutDashboardIcon },
      { href: "/admin/autoreply", label: "Auto reply", icon: BotIcon },
      { href: "/admin/models", label: "Models", icon: CpuIcon },
      { href: "/admin/grounding", label: "Grounding plan", icon: MapIcon },
      { href: "/admin/traces", label: "Traces", icon: ActivityIcon },
      { href: "/admin/users", label: "Users and roles", icon: UsersIcon },
    ],
  },
  {
    label: "Simulation", roles: ["operator", "admin"], items: [
      { href: "/sim", label: "Network", icon: NetworkIcon },
      { href: "/sim/scenarios", label: "Incidents", icon: SirenIcon },
      { href: "/sim/customers", label: "Customers", icon: UsersIcon },
      { href: "/sim/requests", label: "Customer requests", icon: ActivityIcon },
      { href: "/sim/lab", label: "Test lab", icon: FlaskConicalIcon },
      { href: "/sim/events", label: "Event log", icon: ScrollTextIcon },
    ],
  },
];
const ROOTS = ["/console", "/admin", "/sim"];
/** The data behind each section's pages, warmed after sign-in so moving between them is instant. */
const WARM: Record<string, string[]> = {
  Console: ["/console/cases?tab=needs_approval"],
  Admin: ["/admin/overview", "/admin/autoreply", "/admin/models/map", "/admin/models/history", "/admin/grounding-plan",
    "/admin/feedback", "/admin/traces?q="],
  Simulation: ["/sim/network", "/sim/scenarios", "/sim/faults", "/sim/subscribers?q=&limit=100", "/sim/events?limit=200",
    "/lab/runs", "/lab/requests?q="],
};

const EASE = "duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]";
/** The current page: a light violet tint with a thin bar on its left edge. */
const ACTIVE = "rounded-lg data-active:bg-primary/10 data-active:text-foreground data-active:shadow-[inset_2px_0_0_var(--primary)] data-active:[&_svg]:text-primary";

/**
 * The full logo when expanded, the mark alone when collapsed. The mark is the logo's left
 * edge, so one clipping frame that narrows to it turns one into the other. Collapsed, the mark
 * is the button that opens the sidebar again; the fold control only shows when expanded.
 */
function SidebarBrand({ home }: { home: string }) {
  const { state, toggleSidebar } = useSidebar();
  const collapsed = state === "collapsed";
  const h = 28;
  return (
    <SidebarHeader className="flex-row items-center gap-2 px-2.5 py-3 group-data-[collapsible=icon]:px-[9px]">
      {collapsed ? (
        <button type="button" onClick={toggleSidebar} aria-label="Expand the sidebar"
                className={cn("shrink-0 overflow-hidden rounded-md transition-[width] outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring", EASE)}
                style={{ width: h + 1, height: h }}>
          <LogoMark className="block max-w-none" style={{ height: h }} />
        </button>
      ) : (
        <Link href={home} aria-label="Lanka Link home" className={cn("shrink-0 overflow-hidden transition-[width]", EASE)}
              style={{ width: Math.ceil(h * LOGO_RATIO) + 1, height: h }}>
          <LogoMark className="block max-w-none" style={{ height: h }} />
        </Link>
      )}
      <SidebarTrigger className={cn("ml-auto shrink-0 transition-[opacity,width]", EASE,
        "group-data-[collapsible=icon]:pointer-events-none group-data-[collapsible=icon]:w-0 group-data-[collapsible=icon]:opacity-0")} />
    </SidebarHeader>
  );
}

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

  useEffect(() => {
    if (!data?.user) return;
    const t = setTimeout(() => GROUPS.filter((g) => g.roles.includes(role)).flatMap((g) => WARM[g.label] ?? [])
      .forEach(prefetch), 400); // after the current page's own requests
    return () => clearTimeout(t);
  }, [data?.user, role]);

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon">
        {/* The fold control lives in the sidebar's own corner, and stays reachable when collapsed. */}
        <SidebarBrand home={role === "operator" ? "/sim" : role === "admin" ? "/admin" : "/console"} />
        <SidebarContent>
          {GROUPS.filter((g) => g.roles.includes(role)).map((g) => (
            <SidebarGroup key={g.label}>
              <SidebarGroupLabel className="text-[11px] font-medium tracking-wider uppercase text-sidebar-foreground/50">{g.label}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {g.items.map(({ href, label, icon: Icon }) => {
                    const active = ROOTS.includes(href)
                      ? path === href || (href === "/console" && path.startsWith("/console/"))
                      : path.startsWith(href);
                    return (
                      <SidebarMenuItem key={href}>
                        <SidebarMenuButton isActive={active} tooltip={label} render={<Link href={href} />} className={ACTIVE}>
                          <Icon />
                          <span className="whitespace-nowrap transition-opacity duration-300 group-data-[collapsible=icon]:opacity-0">{label}</span>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    );
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
        </SidebarContent>
        <SidebarFooter className="px-3 pb-4 text-sm">
          <div className="flex min-w-0 max-h-14 items-center gap-2.5 overflow-hidden rounded-xl border border-sidebar-border bg-sidebar-accent/40 p-2 whitespace-nowrap transition-[max-height,opacity,padding] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] group-data-[collapsible=icon]:max-h-0 group-data-[collapsible=icon]:border-0 group-data-[collapsible=icon]:p-0 group-data-[collapsible=icon]:opacity-0">
            <span aria-hidden className="relative grid size-8 shrink-0 place-items-center rounded-full bg-primary text-sm font-semibold text-white">
              {data?.user.name?.slice(0, 1).toUpperCase()}
              <span className="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full border-2 border-sidebar bg-success" />
            </span>
            <span className="min-w-0">
              <span className="block truncate font-medium">{data?.user.name}</span>
              <span className="block text-[11px] font-medium tracking-wider uppercase text-muted-foreground">{role}</span>
            </span>
          </div>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton tooltip="Lanka Link website" render={<Link href="/" />}>
                <GlobeIcon />
                <span className="whitespace-nowrap transition-opacity duration-300 group-data-[collapsible=icon]:opacity-0">Website</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton tooltip="Sign out" onClick={() => signOutTo(router, "/sign-in")}>
                <LogOutIcon />
                <span className="whitespace-nowrap transition-opacity duration-300 group-data-[collapsible=icon]:opacity-0">Sign out</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset className="relative isolate !bg-transparent text-sm">
        <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b border-foreground/5 bg-background/60 px-3 backdrop-blur-xl md:px-5">
          <SidebarTrigger className="size-10 md:hidden" />
          <LogoIcon className="size-7 shrink-0 md:hidden" />
          {bar}
          {role !== "operator" && (
            <span className="ml-auto hidden items-center gap-2 text-xs text-muted-foreground sm:flex">
              <kbd className="rounded-md border border-foreground/10 bg-muted/60 px-1.5 py-0.5 font-sans text-[11px] font-medium">Ctrl K</kbd> find a case
            </span>
          )}
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-6 lg:p-8">{children}</main>
      </SidebarInset>
      {role !== "operator" && <JumpToCase />}
    </SidebarProvider>
  );
}

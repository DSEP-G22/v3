import Link from "next/link";

import { DocsNav } from "@/components/docs-nav";
import { SiteHeader } from "@/components/site-header";

export const metadata = { title: "How Lanka Link works" };

const SECTIONS = [
  { id: "overview", title: "Overview" },
  { id: "customers", title: "For customers" },
  { id: "tickets", title: "How a ticket flows" },
  { id: "priorities", title: "Two priorities" },
  { id: "replies", title: "How replies are written" },
  { id: "agents", title: "For agents" },
  { id: "admins", title: "For admins" },
  { id: "simulation", title: "The simulation" },
  { id: "models", title: "Models and retraining" },
  { id: "tracing", title: "Tracing" },
  { id: "running", title: "Running it" },
];

const SURFACES = [
  { path: "/app", who: "Customers", what: "Tickets, billing, usage and plan." },
  { path: "/console", who: "Agents", what: "The queue, the draft, approve or send back." },
  { path: "/admin", who: "Admins", what: "Auto reply, models, grounding and traces." },
  { path: "/sim", who: "Operators", what: "The simulated network and a test lab." },
];

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  const n = SECTIONS.findIndex((s) => s.id === id) + 1;
  return (
    <section id={id} className="scroll-mt-32 border-b border-foreground/10 pb-12 last:border-0 lg:scroll-mt-24">
      <p className="font-pixel text-lg leading-none text-primary">{String(n).padStart(2, "0")}</p>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight">{title}</h2>
      <div className="mt-4 space-y-4 text-[15px] leading-relaxed text-muted-foreground [&_li::marker]:text-primary/60 [&_strong]:font-medium [&_strong]:text-foreground">{children}</div>
    </section>
  );
}

/** A command block, framed like a terminal window. */
function Code({ children }: { children: string }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-foreground/10 bg-[oklch(0.16_0.03_295)] text-[oklch(0.92_0.02_300)] shadow-lg shadow-primary/5">
      <div className="flex items-center gap-1.5 border-b border-white/10 px-4 py-2.5">
        {["bg-destructive/70", "bg-warning/70", "bg-success/70"].map((c) => <span key={c} aria-hidden className={`size-2.5 rounded-full ${c}`} />)}
        <span className="pixel-label ml-2 text-[14px] text-white/40">Terminal</span>
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-xs leading-relaxed">{children}</pre>
    </div>
  );
}

export default function Docs() {
  return (
    <>
      <SiteHeader />
      <div className="relative isolate">
        <header className="mx-auto w-full max-w-6xl px-4 pt-14 pb-10 sm:pt-20">
          <p className="pixel-label text-[17px] text-primary">Documentation</p>
          <h1 className="mt-3 max-w-3xl text-4xl leading-[1.05] font-semibold tracking-tight text-balance sm:text-5xl">
            How Lanka Link <span className="font-pixel font-normal text-primary">works</span>
          </h1>
          <p className="mt-4 max-w-2xl text-base text-muted-foreground sm:text-lg">
            The customer app, the agent console, the admin area and the simulation, and what happens between a
            customer opening a ticket and reading the reply.
          </p>
          <ul className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {SURFACES.map((s) => (
              <li key={s.path} className="rounded-2xl border border-foreground/10 bg-background/60 p-4 backdrop-blur">
                <p className="font-pixel text-xl leading-none text-primary">{s.path}</p>
                <p className="mt-3 font-medium">{s.who}</p>
                <p className="mt-0.5 text-sm text-muted-foreground">{s.what}</p>
              </li>
            ))}
          </ul>
        </header>
      </div>

      {/* A phone reads with the contents as a sticky row of chips under the header. */}
      <div className="sticky top-16 z-20 border-y border-foreground/5 bg-background/80 px-4 backdrop-blur-xl lg:hidden">
        <DocsNav sections={SECTIONS} variant="chips" />
      </div>

      <div className="mx-auto grid w-full max-w-6xl gap-12 px-4 pt-10 pb-24 lg:grid-cols-[15rem_1fr]">
        <aside className="hidden lg:block">
          <div className="sticky top-24"><DocsNav sections={SECTIONS} variant="rail" /></div>
        </aside>

        <article className="min-w-0 max-w-3xl space-y-12 [overflow-wrap:anywhere]">
          <Section id="overview" title="Overview">
            <p>
              Lanka Link is a telecom operator with a support system that reads every request against the customer&apos;s
              own line, account and area before anyone replies. It runs as a set of services behind one address,
              <strong> http://localhost:8080</strong>.
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li><strong>/app</strong>: customers. Home, tickets, billing, usage, plan and settings.</li>
              <li><strong>/console</strong>: agents and leads. The queue, the draft, approve or send back.</li>
              <li><strong>/admin</strong>: admins. Auto reply, models, grounding plan, traces, feedback and users.</li>
              <li><strong>/sim</strong>: operators. The simulated network, incidents, customers and a test lab.</li>
            </ul>
          </Section>

          <Section id="customers" title="For customers">
            <p>
              Support works as <strong>tickets</strong>. A ticket has a subject, a category and a thread. Customers
              can attach photos of the router and voice notes, and reply on the same ticket as often as they need.
              A reply on a closed ticket reopens it.
            </p>
            <p>
              When something on our side affects them, the ticket shows it as a <strong>notice</strong>: repair work
              in the area with its estimate, a paused service with the amount to pay, planned maintenance with its
              window, busy evening hours, or a used up data allowance. These appear before anyone has to write back.
            </p>
            <p>
              Past tickets are shown as a timeline. Answered and closed tickets ask for a rating from one to five
              and an optional comment, which admins see under feedback.
            </p>
          </Section>

          <Section id="tickets" title="How a ticket flows">
            <ol className="list-decimal space-y-1 pl-5">
              <li><strong>Intake</strong> stores the message and attachments and opens or revises a case.</li>
              <li><strong>In parallel</strong>: translation to English, speech to text, photo analysis and an account prefetch.</li>
              <li><strong>Triage</strong> routes to a department by rules and scores the request with the TriageModel.</li>
              <li><strong>Diagnosis</strong> retrieves procedures and names a likely fault.</li>
              <li><strong>Grounding</strong> assembles the one bundle of facts the writer may use, and scores our side.</li>
              <li><strong>Response</strong> drafts from that bundle only, checks every sentence, then releases or holds for an agent.</li>
            </ol>
            <p>Each stage has a time budget. A late stage marks the case as partial rather than holding it up.</p>
          </Section>

          <Section id="priorities" title="Two priorities">
            <p>Every case carries two separate priorities on the one to ten scale.</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <strong>Customer side</strong>, from the distilled TriageModel: a MiniLM embedding of the request plus
                eighteen engineered signals (urgency words, sentiment, repeat contact, photos, error codes, account
                segment and service level age). It predicts an urgency band and a score.
              </li>
              <li>
                <strong>Our side</strong>, from rules over the account and network records: an open outage, a line our
                equipment cannot see, a barred account, an unusual charge, maintenance, congestion. The worst
                finding sets the level, raised for service tier and service level risk.
              </li>
            </ul>
            <p>The queue sorts by the higher of the two. The console shows both, each with its reasons.</p>
          </Section>

          <Section id="replies" title="How replies are written">
            <p>
              The writer sees one bundle and nothing else. Replies <strong>open with the customer&apos;s own side</strong>
              (a loose cable, a red light, the Wi-Fi) with steps taken only from the device guidance and procedures,
              then cover anything on our side in a separate paragraph, because fixing one side alone may not restore
              the service. No amount, date or step is ever invented.
            </p>
            <p>
              Every sentence is checked as it streams: no refund promises, no guarantees, no personal data, no
              actions the customer is not entitled to. One failed check holds the reply for an agent.
            </p>
          </Section>

          <Section id="agents" title="For agents">
            <p>
              The console queue lists cases by priority with both sides shown. A case shows what the customer sent,
              what we found, why it has its priority, and the draft. Agents approve, edit, send back or escalate.
              Ctrl K finds any case.
            </p>
          </Section>

          <Section id="admins" title="For admins">
            <ul className="list-disc space-y-1 pl-5">
              <li><strong>Auto reply</strong>: per department, whether a clean, low priority draft may go out without review.</li>
              <li><strong>Models</strong>: swap the drafting and diagnosis models live (Ollama, Gemini, or the offline stand in) and probe them.</li>
              <li><strong>Grounding plan</strong>: which facts each department checks, with a dry run against a real customer.</li>
              <li><strong>Traces</strong>: every stage of every case with timings, and the bundle the writer saw.</li>
              <li><strong>Feedback</strong>: average rating and the latest comments, on the overview.</li>
            </ul>
          </Section>

          <Section id="simulation" title="The simulation">
            <p>
              The business behind the app is simulated: exchanges, OLTs, lines, routers, invoices and usage move on
              a sim clock you can pause, speed up or jump forward. The panel is split in two:
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li><strong>Network</strong>: the live topology. Click equipment to open an outage, congest it or schedule maintenance.</li>
              <li><strong>Incidents</strong>: network scenarios and customer scenarios, and the board of active faults to clear.</li>
              <li><strong>Customers</strong>: accounts, line charts and customer scenarios such as a suspension or a crashing router.</li>
              <li><strong>Test lab</strong>: send a message as any customer and watch every stage live.</li>
            </ul>
          </Section>

          <Section id="models" title="Models and retraining">
            <p>
              The TriageModel lives in <strong>TriageModel/</strong>: a labelled corpus, an LLM labelling pass and a
              distilled multi task head. The triage service runs its exported numpy weights, so it needs no torch.
            </p>
            <p>
              Retraining is a <strong>DVC</strong> pipeline (train, export, evaluate) driven weekly by an
              <strong> Airflow</strong> DAG. Every run is logged to <strong>MLflow</strong>. A candidate that beats
              the production model on the gold set, inside the latency budget, is promoted into the shared model
              volume and the triage service reloads it without a restart.
            </p>
            <Code>{`docker compose --profile mlops up -d      # MLflow on :5000, Airflow on :8081
cd ml && dvc repro                        # the same pipeline by hand`}</Code>
          </Section>

          <Section id="tracing" title="Tracing">
            <p>
              With <strong>LANGSMITH_TRACING=true</strong> and a key, each case revision is one LangSmith trace:
              every pipeline stage nests under it with its inputs and outputs, and the draft appears as an LLM run
              with the exact prompt the writer saw.
            </p>
          </Section>

          <Section id="running" title="Running it">
            <Code>{`cp .env.example .env              # NEON_KEY, BETTER_AUTH_SECRET, optional keys
docker compose up -d --wait        # everything
docker compose -f compose.yaml -f compose.lite.yaml up -d --wait   # every stage, translation and speech included
uv run python scripts/demo_flow.py # the headline case end to end`}</Code>
            <p>
              Seeded logins: <strong>agent1</strong>, <strong>lead1</strong>, <strong>admin1</strong> and
              <strong> operator1</strong> at lankalink.example.lk for staff, and eight customers at
              customers.lankalink.example.lk. See the <Link href="/plans" className="text-primary underline underline-offset-4">plans</Link> to sign up as a new one.
            </p>
          </Section>
        </article>
      </div>
    </>
  );
}

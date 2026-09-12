import { auth, pool } from "./auth.js";

// Staff logins. Idempotent.
const STAFF: Array<[email: string, role: string, name: string]> = [
  ["agent1@lankalink.example.lk", "agent", "Nadeesha Perera"],
  ["lead1@lankalink.example.lk", "lead", "Ruwan Jayasuriya"],
  ["admin1@lankalink.example.lk", "admin", "Chamari Silva"],
  ["operator1@lankalink.example.lk", "operator", "Kasun Fernando"],
];

// The eight v2 personas as customer logins, linked to their subscribers in business.
const PERSONAS: Array<[email: string, name: string, subscriber: string, language: string]> = [
  ["amara@customers.lankalink.example.lk", "Amara Perera", "SUB-100001", "en"],
  ["ravi@customers.lankalink.example.lk", "Ravi Fernando", "SUB-100002", "si"],
  ["nadia@customers.lankalink.example.lk", "Nadia Silva", "SUB-100003", "en"],
  ["dinesh@customers.lankalink.example.lk", "Dinesh Jayawardena", "SUB-100004", "en"],
  ["priya@customers.lankalink.example.lk", "Priya Kumar", "SUB-100005", "en"],
  ["kavindu@customers.lankalink.example.lk", "Kavindu Rathnayake", "SUB-100006", "en"],
  ["thilini@customers.lankalink.example.lk", "Thilini Wickramasinghe", "SUB-100007", "en"],
  ["rizwan@customers.lankalink.example.lk", "Mohamed Rizwan", "SUB-100008", "ta"],
];

async function ensureUser(email: string, password: string, name: string, role: string, language = "en") {
  const found = await pool.query('SELECT id FROM "user" WHERE email = $1', [email]);
  if (!found.rowCount) {
    await auth.api.signUpEmail({ body: { email, password, name } });
  }
  const { rows } = await pool.query(
    'UPDATE "user" SET role = $1, "emailVerified" = true, "preferredLanguage" = $3 WHERE email = $2 RETURNING id',
    [role, email, language],
  );
  return rows[0].id as string;
}

export async function seedStaff(password: string | undefined): Promise<void> {
  if (!password) return;
  for (const [email, role, name] of STAFF) await ensureUser(email, password, name, role);
  console.log(`auth: ${STAFF.length} staff logins ready`);
}

/** Persona logins now; their subscriber links as soon as business is up (it starts later). */
export async function seedPersonas(password: string | undefined): Promise<void> {
  if (!password) return;
  const links: Array<[string, string]> = [];
  for (const [email, name, subscriber, language] of PERSONAS) {
    links.push([await ensureUser(email, password, name, "customer", language), subscriber]);
  }
  const business = process.env.BUSINESS_URL ?? "http://business:8000";
  void (async () => {
    for (let attempt = 0; attempt < 120 && links.length; attempt++) {
      for (const [userId, subscriber] of [...links]) {
        try {
          const r = await fetch(`${business}/links`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ user_id: userId, subscriber_ref: subscriber, linked_by: "seed" }),
          });
          if (r.ok) links.splice(links.findIndex(([u]) => u === userId), 1);
        } catch {
          // business not up yet
        }
      }
      if (links.length) await new Promise((res) => setTimeout(res, 5000));
    }
    console.log(links.length ? `auth: ${links.length} persona links still pending` : "auth: persona logins linked");
  })();
}

import { redirect } from "next/navigation";

/** Support moved to tickets; old links land in the right place. */
export default function Support() {
  redirect("/app/tickets");
}

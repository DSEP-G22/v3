import { createAuthClient } from "better-auth/react";
import { adminClient, jwtClient } from "better-auth/client/plugins";

// Same origin as the page: Caddy routes /api/auth/* to the auth service.
export const authClient = createAuthClient({ plugins: [jwtClient(), adminClient()] });

export const { signIn, signUp, signOut, useSession } = authClient;

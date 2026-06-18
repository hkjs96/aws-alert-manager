import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

/**
 * Auth.js (NextAuth v5) — Google SSO.
 *
 * The Google-issued ID token is forwarded by the API proxy
 * (`app/api/[...path]/route.ts`) as `Authorization: Bearer`, where API
 * Gateway's native JWT authorizer validates it. The email/domain allowlist is
 * enforced authoritatively in the backend; the `signIn` check below is a
 * convenience UX gate so disallowed users never reach the app shell.
 *
 * Auth is optional: with no `AUTH_GOOGLE_ID`/`AUTH_SECRET` configured the app
 * runs unauthenticated (mirrors the backend's empty-GoogleClientId behavior),
 * which keeps local development frictionless.
 */

function csv(value: string | undefined): string[] {
  return (value ?? "")
    .split(",")
    .map((part) => part.trim().toLowerCase().replace(/^@/, ""))
    .filter(Boolean);
}

const ALLOWED_EMAILS = csv(process.env.ALLOWED_EMAILS);
const ALLOWED_DOMAINS = csv(process.env.ALLOWED_EMAIL_DOMAINS);

function isAllowed(email: string, hostedDomain: string): boolean {
  if (ALLOWED_EMAILS.length === 0 && ALLOWED_DOMAINS.length === 0) {
    return true;
  }
  const normalized = email.toLowerCase();
  if (ALLOWED_EMAILS.includes(normalized)) {
    return true;
  }
  const domain = normalized.includes("@") ? normalized.split("@").pop()! : "";
  const hd = hostedDomain.toLowerCase();
  return (
    (domain.length > 0 && ALLOWED_DOMAINS.includes(domain)) ||
    (hd.length > 0 && ALLOWED_DOMAINS.includes(hd))
  );
}

type GoogleProfileFields = {
  email?: string;
  email_verified?: boolean;
  hd?: string;
};

type GoogleTokenResponse = {
  id_token?: string;
  expires_in?: number;
  refresh_token?: string;
};

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Google({
      // Request offline access so we receive a refresh token and can mint a
      // fresh ID token after the ~1h expiry without forcing re-login.
      authorization: { params: { access_type: "offline", prompt: "consent" } },
    }),
  ],
  pages: { signIn: "/login" },
  session: {
    strategy: "jwt",
    maxAge: 60 * 60 * 8, // 8시간 (근무일 세션) — 미활동 8시간 후 만료
    updateAge: 60 * 60, // 활동 시 1시간마다 rolling 갱신
  },
  callbacks: {
    signIn({ profile }) {
      const p = profile as GoogleProfileFields | undefined;
      if (p?.email_verified === false) {
        return false;
      }
      return isAllowed(p?.email ?? "", p?.hd ?? "");
    },
    async jwt({ token, account }) {
      // Initial sign-in: capture the Google tokens.
      if (account) {
        token.id_token = account.id_token;
        token.refresh_token = account.refresh_token;
        token.expires_at = account.expires_at;
        return token;
      }
      // Still valid (60s skew buffer) → reuse.
      if (token.expires_at && Date.now() < token.expires_at * 1000 - 60_000) {
        return token;
      }
      // Expired → refresh the ID token via Google's token endpoint.
      if (!token.refresh_token) {
        token.error = "RefreshTokenError";
        return token;
      }
      try {
        const response = await fetch("https://oauth2.googleapis.com/token", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({
            client_id: process.env.AUTH_GOOGLE_ID ?? "",
            client_secret: process.env.AUTH_GOOGLE_SECRET ?? "",
            grant_type: "refresh_token",
            refresh_token: token.refresh_token,
          }),
        });
        const refreshed = (await response.json()) as GoogleTokenResponse;
        if (!response.ok) {
          throw new Error("token refresh failed");
        }
        token.id_token = refreshed.id_token ?? token.id_token;
        if (typeof refreshed.expires_in === "number") {
          token.expires_at = Math.floor(Date.now() / 1000 + refreshed.expires_in);
        }
        if (refreshed.refresh_token) {
          token.refresh_token = refreshed.refresh_token;
        }
        delete token.error;
      } catch {
        token.error = "RefreshTokenError";
      }
      return token;
    },
    authorized({ auth: session }) {
      return Boolean(session?.user);
    },
    session({ session, token }) {
      // Expose the ID token + error to server-side callers (proxy/SSR) via auth().
      session.id_token = token.id_token;
      if (token.error) {
        session.error = token.error;
      }
      return session;
    },
  },
});

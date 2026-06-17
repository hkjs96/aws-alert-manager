import "next-auth/jwt";
import "next-auth";

declare module "next-auth/jwt" {
  interface JWT {
    /** Google-issued ID token, forwarded to API Gateway as a Bearer token. */
    id_token?: string;
    refresh_token?: string;
    /** ID token expiry as a UNIX timestamp (seconds). */
    expires_at?: number;
    error?: "RefreshTokenError";
  }
}

declare module "next-auth" {
  interface Session {
    /** Google ID token, exposed so server-side code (proxy/SSR) can forward it
     *  as a Bearer token via auth(). This is the user's own token. */
    id_token?: string;
    error?: "RefreshTokenError";
  }
}

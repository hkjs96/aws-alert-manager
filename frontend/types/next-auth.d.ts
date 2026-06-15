import "next-auth/jwt";

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

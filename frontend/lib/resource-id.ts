/**
 * 리소스 URL 식별자 인코딩 (base64url 불투명 토큰).
 *
 * EC2 instance-id(`i-...`)처럼 슬래시 없는 resource_id도 있지만 ALB/NLB/TG는
 * 풀 ARN(`arn:...:targetgroup/name/hash`)이라 `/`·`:`를 포함한다. 이런 값을 URL
 * path 세그먼트나 API path에 그대로 넣으면 브라우저/CloudFront/Next 프록시
 * (`app/api/[...path]`)/API Gateway가 `%2F`를 다시 `/`로 디코딩하면서 라우팅이
 * 깨진다(상세: 루트 AGENTS.md AP-6).
 *
 * 그래서 resource_id를 base64url로 인코딩해 `/`·`:`·`%`가 없는 토큰으로 만든 뒤
 * 모든 path 진입점에 싣는다. 백엔드 `_decode_resource_token`이 역변환한다.
 * 가역(reversible) 토큰이라 별도 매핑 테이블/GSI 없이 그대로 복원되고,
 * 타입 무관(type-agnostic)이라 신규 리소스 추가 시 별도 작업이 필요 없다.
 */

const TOKEN_PREFIX = "r.";

function toBase64Url(input: string): string {
  const bytes = new TextEncoder().encode(input);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(payload: string): string {
  const b64 = payload.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  const bytes = Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

/**
 * 원본 resource_id → URL-safe 토큰.
 * resource_id를 URL path나 API path에 넣는 모든 지점에서 반드시 경유한다.
 */
export function encodeResourceId(resourceId: string): string {
  return TOKEN_PREFIX + toBase64Url(resourceId);
}

/**
 * 토큰 → 원본 resource_id.
 * 토큰이 아니면(레거시 raw id / 리소스 name) 입력을 그대로 반환한다.
 * page의 `params.id`를 원본 id로 복원할 때 사용한다.
 */
export function decodeResourceId(token: string): string {
  if (!token.startsWith(TOKEN_PREFIX)) return token;
  try {
    const decoded = fromBase64Url(token.slice(TOKEN_PREFIX.length));
    // round-trip 가드: 정상 토큰만 복원하고, 우연히 접두사가 겹친 raw 값은 보존한다.
    if (encodeResourceId(decoded) === token) return decoded;
  } catch {
    /* malformed → raw 폴백 */
  }
  return token;
}

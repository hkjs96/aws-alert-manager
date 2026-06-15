# 인증 (Google SSO)

AWS Alert Manager는 **Google SSO**로 인증한다. Cognito·자체 사용자 DB
없이, 회사 Google Workspace 또는 개인 Google 계정으로 로그인한다.

## 구조 (2계층)

```
브라우저 ──login──> Next.js (Auth.js + Google)
                      │  세션에 Google ID 토큰 보관 (서버 전용)
                      ▼
        API 프록시 app/api/[...path]
                      │  Authorization: Bearer <google id_token>
                      ▼
        API Gateway v2  ── 네이티브 JWT authorizer (서명·iss·aud·exp 검증)
                      ▼
        api_handler Lambda ── email/도메인 allowlist 강제 (백엔드 권위)
```

- **토큰 진위**는 API Gateway의 네이티브 JWT authorizer가 검증한다.
  코드·Cognito·커스텀 Lambda 없이 CloudFormation 설정만으로 동작한다.
- **누가 허용되는가**(allowlist)는 `api_handler`가 authorizer가 검증한
  claims(`email`/`hd`)로 강제한다. 이것이 **유일한 권위 있는 접근 제어**다.
  프론트엔드 `signIn` 체크는 UX 편의용일 뿐이다.

## 단계적 활성화 (락아웃 방지)

`GoogleClientId`가 **비어 있으면 API는 public**(현재 동작), 값이 있으면 JWT
authorizer가 강제된다. 코드를 먼저 배포하고 인증을 나중에 켤 수 있다.
allowlist(`ALLOWED_EMAILS`/`ALLOWED_EMAIL_DOMAINS`)도 비어 있으면 무제한이다.

## 1. Google OAuth 클라이언트 생성

1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
   → **사용자 인증 정보 만들기** → **OAuth 클라이언트 ID** → 유형 **웹 애플리케이션**.
2. **승인된 리디렉션 URI**에 추가:
   - `http://localhost:3000/api/auth/callback/google` (로컬)
   - `https://<배포도메인>/api/auth/callback/google` (배포)
3. 발급된 **클라이언트 ID**와 **클라이언트 보안 비밀**을 보관.

## ⚠️ 필수 전제: 클라이언트는 프록시를 경유해야 한다

ID 토큰은 **서버 전용**이라 브라우저에 노출되지 않는다. 따라서 인증을 켜면
클라이언트 요청이 반드시 Next.js 프록시(`/api/...`, same-origin)를 거쳐야
하며, 프록시가 `Authorization: Bearer`를 붙인다.

`apiFetch`는 `NEXT_PUBLIC_API_BASE_URL`이 설정돼 있으면 **브라우저가 API
Gateway를 직접 호출**(프록시 우회)한다. 이 경우 토큰이 없어 인증 켜는 순간
모든 요청이 401이 된다. **인증을 켤 때는:**

- `NEXT_PUBLIC_API_BASE_URL` → **비워 둔다**(클라이언트가 `/api/*` 상대경로 사용).
- `API_GATEWAY_URL`(서버 전용) → API Gateway URL로 설정(프록시가 사용).

배포가 AWS Amplify면 위 두 값은 **Amplify 콘솔 환경변수**로 설정한다
(`.env.production`은 비워 둔다 — Amplify 주입값을 덮어쓰지 않도록).

## 2. 프론트엔드 환경변수 (`frontend/.env.local`)

```bash
AUTH_GOOGLE_ID=<클라이언트 ID>
AUTH_GOOGLE_SECRET=<클라이언트 보안 비밀>
AUTH_SECRET=<openssl rand -base64 32>
# 배포 시: AUTH_URL=https://<배포도메인>

# allowlist (백엔드와 동일하게)
ALLOWED_EMAILS=me@gmail.com
ALLOWED_EMAIL_DOMAINS=company.com
```

4개(`AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET`/`AUTH_SECRET`)가 비어 있으면
프론트엔드는 인증 없이 동작한다(로컬 개발용).

## 3. 백엔드 배포 (인증 켜기)

`GoogleClientId`는 위 **클라이언트 ID와 동일**해야 한다(JWT authorizer의
audience). allowlist도 동일하게 맞춘다. 배포 시 환경변수로 전달한다:

```bash
$env:GOOGLE_CLIENT_ID = "<클라이언트 ID>"
$env:ALLOWED_EMAILS = "me@gmail.com"
$env:ALLOWED_EMAIL_DOMAINS = "company.com"
python .codex/deploy-backend-stack.py --all-artifacts
```

이 값들은 CloudFormation 파라미터로 전달되며, 한 번 설정하면 이후
코드만 배포할 때(`GOOGLE_CLIENT_ID` 미전달) 이전 값이 유지된다
(CFN `UsePreviousValue`).

## allowlist 규칙

- `ALLOWED_EMAILS`: 개별 이메일 정확 매칭 (개인 gmail 등).
- `ALLOWED_EMAIL_DOMAINS`: 이메일 도메인 또는 Google Workspace `hd` 클레임 매칭.
- 둘 중 **하나라도** 매칭되면 허용. 둘 다 비어 있으면 무제한.
- `email_verified=false` 토큰은 거부.
- `GET /health`는 allowlist 면제(가동 모니터링용).

## 라이브러리 버전

프론트엔드는 `next-auth@5.0.0-beta.31`을 **정확히 핀**한다(캐럿 없음).
Next 15 + React 19 App Router에는 정식(non-beta) next-auth가 없으며, v5는
Vercel이 직접 유지하는 사실상 표준이다("beta"는 API 표면 미확정 라벨일 뿐).
정식 라벨이 필요하면 `better-auth`(1.x)가 대안이나, auth 레이어 재작성이 따른다.

## 토큰 갱신

Google ID 토큰은 ~1시간 후 만료된다. Auth.js의 `jwt` 콜백이 refresh
토큰으로 새 ID 토큰을 발급해 재로그인 없이 갱신한다(`access_type=offline`).

## 알려진 후속 작업 (UX 폴리시)

- `/login` 페이지가 현재 루트 레이아웃의 `AppShell`(사이드바) 안에 렌더된다.
  라우트 그룹으로 분리하면 깔끔하다.
- 로그아웃 버튼: `next-auth/react`의 `signOut()`을 `AppShell` 헤더에 추가.

import { describe, it, expect } from "vitest";
import { encodeResourceId, decodeResourceId } from "../resource-id";

const TG_ARN =
  "arn:aws:elasticloadbalancing:us-east-1:949501913924:" +
  "targetgroup/dev-e2e-alb-tg-ip/ef28a16dfd6f7523";

describe("encodeResourceId / decodeResourceId", () => {
  it("ARN을 라운드트립한다", () => {
    expect(decodeResourceId(encodeResourceId(TG_ARN))).toBe(TG_ARN);
  });

  it("EC2 instance-id를 라운드트립한다", () => {
    expect(decodeResourceId(encodeResourceId("i-04fdf4b064295b776"))).toBe(
      "i-04fdf4b064295b776",
    );
  });

  it("토큰에는 슬래시·콜론·퍼센트가 없다 (모든 path 홉을 통과)", () => {
    const token = encodeResourceId(TG_ARN);
    expect(token).not.toMatch(/[/:%]/);
  });

  it("base64url 토큰은 url-unreserved 문자만 사용한다", () => {
    // encodeURIComponent를 거쳐도 변하지 않아야 프록시/게이트웨이를 안전 통과한다.
    const token = encodeResourceId(TG_ARN);
    expect(encodeURIComponent(token)).toBe(token);
  });

  it("토큰이 아닌 값(레거시 raw id)은 그대로 통과시킨다", () => {
    expect(decodeResourceId("i-04fdf4b064295b776")).toBe("i-04fdf4b064295b776");
    expect(decodeResourceId("my-resource-name")).toBe("my-resource-name");
  });

  it("접두사만 겹치고 토큰이 아닌 값은 보존한다", () => {
    // `.`은 base64url 알파벳이 아니라 디코딩 실패 → 원본 보존 (S3 버킷 등).
    expect(decodeResourceId("r.example.com")).toBe("r.example.com");
  });
});

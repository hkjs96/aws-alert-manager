"use client";

import { useCallback, useEffect, useRef } from "react";
import { useReportWebVitals } from "next/web-vitals";
import { usePathname } from "next/navigation";

/**
 * 실사용자 성능(RUM) 수집 — Web Vitals를 모아 /api/vitals로 1회 전송한다.
 *
 * 왜 모아서 보내나: LCP·CLS·INP는 확정 시점이 서로 달라 도착할 때마다 보내면
 * 페이지 진입 1회당 요청이 4~6건이 된다. 페이지를 떠날 때 한 번만 보내면
 * Amplify SSR 요청 수가 페이지뷰와 같아진다(무료 구간 50만/월 안).
 *
 * sendBeacon을 쓰는 이유: 페이지 언로드 중에는 일반 fetch가 취소될 수 있다.
 * 실패해도 조용히 버린다 — 계측이 사용자 경험을 건드리면 안 된다.
 */

interface VitalSample {
  name: string;
  value: number;
  rating: string;
}

/** 페이지뷰당 전송 확률. 1 = 전량. 트래픽이 늘면 낮춰 로그 수집량을 조절한다. */
const SAMPLE_RATE = 1;

export function WebVitals() {
  const pathname = usePathname();
  const buffer = useRef<Map<string, VitalSample>>(new Map());
  const sent = useRef(false);
  // 측정은 진입한 경로에 귀속돼야 한다. 라우트 변경 시점의 pathname을 쓰면
  // 이전 페이지의 LCP가 다음 페이지 이름으로 기록된다.
  const pageRef = useRef(pathname);

  useReportWebVitals((metric) => {
    // 같은 이름이 여러 번 오면(예: CLS 누적) 마지막 값이 최종값이다.
    buffer.current.set(metric.name, {
      name: metric.name,
      value: Math.round(metric.value * 1000) / 1000,
      rating: metric.rating ?? "",
    });
  });

  const flush = useCallback(() => {
    if (sent.current || buffer.current.size === 0) return;
    if (Math.random() > SAMPLE_RATE) {
      sent.current = true;
      return;
    }
    sent.current = true;

    const payload = {
      page: pageRef.current,
      metrics: [...buffer.current.values()],
      // 느린 네트워크와 느린 페이지를 구분하려면 회선 정보가 필요하다 (지원 브라우저만).
      connection:
        (navigator as { connection?: { effectiveType?: string } }).connection?.effectiveType ?? "",
    };

    try {
      const blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
      if (!navigator.sendBeacon?.("/api/vitals", blob)) {
        void fetch("/api/vitals", { method: "POST", body: blob, keepalive: true }).catch(() => {});
      }
    } catch {
      // 계측 실패는 무시한다
    }
  }, []);

  useEffect(() => {
    // 라우트가 바뀌면 이전 페이지 측정을 확정해 보내고, 새 페이지용으로 버퍼를 비운다.
    if (pathname !== pageRef.current) {
      flush();
      buffer.current = new Map();
      sent.current = false;
      pageRef.current = pathname;
    }
  }, [pathname, flush]);

  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") flush();
    };
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", flush);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", flush);
    };
  }, [flush]);

  return null;
}

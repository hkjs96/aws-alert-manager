"use client";

import { useEffect, useState } from "react";
import { fetchMe } from "@/lib/api-functions";

export interface MeState {
  email: string;
  isAdmin: boolean;
  isLoading: boolean;
}

/** 현재 로그인 사용자 정보(이메일/admin 여부)를 조회한다. */
export function useMe(): MeState {
  const [email, setEmail] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetchMe()
      .then((me) => {
        if (!active) return;
        setEmail(me.email);
        setIsAdmin(me.is_admin);
      })
      .catch(() => {
        // 미인증/에러 시 비관리자로 취급
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return { email, isAdmin, isLoading };
}

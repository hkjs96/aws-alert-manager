import {
  Server, Database, MemoryStick, Network, Target, Route, Lock, Cable, Globe,
  Webhook, Cloud, Zap, Container, BrainCircuit, Search, ShieldCheck, Shield,
  Archive, HardDrive, Box, Inbox, Bell, MessageSquare, Workflow,
  type LucideIcon,
} from "lucide-react";

interface TypeStyle {
  icon: LucideIcon;
  /** Tailwind text + bg classes (literal so JIT keeps them). */
  color: string;
}

const FALLBACK: TypeStyle = { icon: Box, color: "text-slate-600 bg-slate-100 ring-slate-200" };

// 카테고리별 색상으로 묶고, 타입마다 대표 아이콘 매핑.
// color = pill 텍스트 + 배경 + 링(테두리) 클래스 (literal 이어야 JIT 유지).
const TYPE_STYLES: Record<string, TypeStyle> = {
  // Compute
  EC2: { icon: Server, color: "text-orange-700 bg-orange-50 ring-orange-200" },
  Lambda: { icon: Zap, color: "text-amber-700 bg-amber-50 ring-amber-200" },
  ECS: { icon: Container, color: "text-blue-700 bg-blue-50 ring-blue-200" },
  SageMaker: { icon: BrainCircuit, color: "text-fuchsia-700 bg-fuchsia-50 ring-fuchsia-200" },
  // Database / cache
  RDS: { icon: Database, color: "text-blue-700 bg-blue-50 ring-blue-200" },
  AuroraRDS: { icon: Database, color: "text-blue-700 bg-blue-50 ring-blue-200" },
  DocDB: { icon: Database, color: "text-blue-700 bg-blue-50 ring-blue-200" },
  DynamoDB: { icon: Database, color: "text-indigo-700 bg-indigo-50 ring-indigo-200" },
  ElastiCache: { icon: MemoryStick, color: "text-rose-700 bg-rose-50 ring-rose-200" },
  // Networking / LB
  ALB: { icon: Network, color: "text-cyan-700 bg-cyan-50 ring-cyan-200" },
  NLB: { icon: Network, color: "text-cyan-700 bg-cyan-50 ring-cyan-200" },
  CLB: { icon: Network, color: "text-cyan-700 bg-cyan-50 ring-cyan-200" },
  TG: { icon: Target, color: "text-cyan-700 bg-cyan-50 ring-cyan-200" },
  NAT: { icon: Route, color: "text-cyan-700 bg-cyan-50 ring-cyan-200" },
  VPN: { icon: Lock, color: "text-cyan-700 bg-cyan-50 ring-cyan-200" },
  DX: { icon: Cable, color: "text-cyan-700 bg-cyan-50 ring-cyan-200" },
  Route53: { icon: Globe, color: "text-cyan-700 bg-cyan-50 ring-cyan-200" },
  APIGW: { icon: Webhook, color: "text-teal-700 bg-teal-50 ring-teal-200" },
  CloudFront: { icon: Cloud, color: "text-sky-700 bg-sky-50 ring-sky-200" },
  // Messaging
  SQS: { icon: Inbox, color: "text-violet-700 bg-violet-50 ring-violet-200" },
  SNS: { icon: Bell, color: "text-violet-700 bg-violet-50 ring-violet-200" },
  MQ: { icon: MessageSquare, color: "text-violet-700 bg-violet-50 ring-violet-200" },
  MSK: { icon: Workflow, color: "text-violet-700 bg-violet-50 ring-violet-200" },
  // Search
  OpenSearch: { icon: Search, color: "text-fuchsia-700 bg-fuchsia-50 ring-fuchsia-200" },
  // Security
  ACM: { icon: ShieldCheck, color: "text-red-700 bg-red-50 ring-red-200" },
  WAF: { icon: Shield, color: "text-red-700 bg-red-50 ring-red-200" },
  // Storage
  S3: { icon: Box, color: "text-emerald-700 bg-emerald-50 ring-emerald-200" },
  EFS: { icon: HardDrive, color: "text-emerald-700 bg-emerald-50 ring-emerald-200" },
  Backup: { icon: Archive, color: "text-emerald-700 bg-emerald-50 ring-emerald-200" },
};

interface ResourceTypeIconProps {
  type: string;
  size?: number;
  className?: string;
}

/** 타입 이름 + 아이콘을 카테고리 색상 pill 배지로 렌더한다. */
export function ResourceTypeIcon({
  type,
  size = 12,
  className = "",
}: ResourceTypeIconProps) {
  const { icon: Icon, color } = TYPE_STYLES[type] ?? FALLBACK;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold leading-none ring-1 ring-inset ${color} ${className}`}
      title={type}
    >
      <Icon size={size} />
      {type}
    </span>
  );
}

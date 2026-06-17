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

const FALLBACK: TypeStyle = { icon: Box, color: "text-slate-500 bg-slate-100" };

// 카테고리별 색상으로 묶고, 타입마다 대표 아이콘 매핑.
const TYPE_STYLES: Record<string, TypeStyle> = {
  // Compute
  EC2: { icon: Server, color: "text-orange-600 bg-orange-50" },
  Lambda: { icon: Zap, color: "text-amber-600 bg-amber-50" },
  ECS: { icon: Container, color: "text-blue-600 bg-blue-50" },
  SageMaker: { icon: BrainCircuit, color: "text-fuchsia-600 bg-fuchsia-50" },
  // Database / cache
  RDS: { icon: Database, color: "text-blue-600 bg-blue-50" },
  AuroraRDS: { icon: Database, color: "text-blue-600 bg-blue-50" },
  DocDB: { icon: Database, color: "text-blue-600 bg-blue-50" },
  DynamoDB: { icon: Database, color: "text-indigo-600 bg-indigo-50" },
  ElastiCache: { icon: MemoryStick, color: "text-rose-600 bg-rose-50" },
  // Networking / LB
  ALB: { icon: Network, color: "text-cyan-700 bg-cyan-50" },
  NLB: { icon: Network, color: "text-cyan-700 bg-cyan-50" },
  CLB: { icon: Network, color: "text-cyan-700 bg-cyan-50" },
  TG: { icon: Target, color: "text-cyan-700 bg-cyan-50" },
  NAT: { icon: Route, color: "text-cyan-700 bg-cyan-50" },
  VPN: { icon: Lock, color: "text-cyan-700 bg-cyan-50" },
  DX: { icon: Cable, color: "text-cyan-700 bg-cyan-50" },
  Route53: { icon: Globe, color: "text-cyan-700 bg-cyan-50" },
  APIGW: { icon: Webhook, color: "text-teal-600 bg-teal-50" },
  CloudFront: { icon: Cloud, color: "text-sky-600 bg-sky-50" },
  // Messaging
  SQS: { icon: Inbox, color: "text-violet-600 bg-violet-50" },
  SNS: { icon: Bell, color: "text-violet-600 bg-violet-50" },
  MQ: { icon: MessageSquare, color: "text-violet-600 bg-violet-50" },
  MSK: { icon: Workflow, color: "text-violet-600 bg-violet-50" },
  // Search
  OpenSearch: { icon: Search, color: "text-fuchsia-600 bg-fuchsia-50" },
  // Security
  ACM: { icon: ShieldCheck, color: "text-red-600 bg-red-50" },
  WAF: { icon: Shield, color: "text-red-600 bg-red-50" },
  // Storage
  S3: { icon: Box, color: "text-emerald-600 bg-emerald-50" },
  EFS: { icon: HardDrive, color: "text-emerald-600 bg-emerald-50" },
  Backup: { icon: Archive, color: "text-emerald-600 bg-emerald-50" },
};

interface ResourceTypeIconProps {
  type: string;
  size?: number;
  showLabel?: boolean;
  className?: string;
}

export function ResourceTypeIcon({
  type,
  size = 16,
  showLabel = false,
  className = "",
}: ResourceTypeIconProps) {
  const { icon: Icon, color } = TYPE_STYLES[type] ?? FALLBACK;
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <span
        className={`inline-flex items-center justify-center rounded-md p-1 ${color}`}
        title={type}
      >
        <Icon size={size} />
      </span>
      {showLabel && <span className="text-xs font-medium text-slate-600">{type}</span>}
    </span>
  );
}

import type { ReactNode } from "react";
import Link from "next/link";
import {
  LogIn, Users, Server, Bell, Search, Boxes, SlidersHorizontal,
  KeyRound, Cloud, Wrench, ArrowLeft,
  Lightbulb, Network, Share2, Workflow, ExternalLink, Download, LayoutGrid,
} from "lucide-react";
import { ResourceTypeIcon } from "@/components/shared/ResourceTypeIcon";

const RESOURCE_GROUPS: { label: string; types: string[] }[] = [
  { label: "Compute", types: ["EC2", "Lambda", "ECS", "SageMaker"] },
  { label: "Database / Cache", types: ["RDS", "AuroraRDS", "DocDB", "DynamoDB", "ElastiCache"] },
  { label: "Network / LB", types: ["ALB", "NLB", "CLB", "TG", "NAT", "VPN", "DX", "Route53", "APIGW", "CloudFront"] },
  { label: "Storage", types: ["S3", "EFS", "Backup"] },
  { label: "Messaging", types: ["SQS", "SNS", "MQ", "MSK"] },
  { label: "Security / Search", types: ["ACM", "WAF", "OpenSearch"] },
];

export const metadata = {
  title: "User Guide · Alarm Manager",
};

type Icon = typeof LogIn;

interface Item {
  icon: Icon;
  title: string;
  body: ReactNode;
}

interface Section {
  id: string;
  label: string;
  intro?: string;
  items: Item[];
}

function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[12px] text-slate-700">
      {children}
    </code>
  );
}

function Block({ children }: { children: ReactNode }) {
  return (
    <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 px-4 py-3 text-[12px] leading-relaxed text-slate-100">
      {children}
    </pre>
  );
}

const SECTIONS: Section[] = [
  {
    id: "user",
    label: "User Guide",
    intro: "The basic workflow every new team member should know.",
    items: [
      {
        icon: LogIn,
        title: "Sign In",
        body: (
          <>Sign in with your company Google account. Only allowed emails/domains can access the app.
          Once signed in, your email and a sign-out button appear in the top right. When your session
          expires, you are sent back to the sign-in screen.</>
        ),
      },
      {
        icon: Users,
        title: "Choosing a Customer/Account Scope",
        body: (
          <>
            Pick what to view from the <b>customer/account dropdowns</b> in the top bar.
            <ul className="ml-4 mt-1.5 list-disc space-y-0.5">
              <li>The dropdown lists only <b>customers where you are one of the managers</b>.</li>
              <li>The selected scope applies to <b>Dashboard, Resources and Alarms</b> and is remembered in this browser.</li>
              <li>Choosing <b>All Customers</b> shows every customer you can access.</li>
            </ul>
          </>
        ),
      },
      {
        icon: Server,
        title: "Resources & Monitoring",
        body: (
          <>
            The <b>Resources</b> screen lists registered AWS resources. Types are shown as colored badges
            (EC2, RDS, S3…).
            <ul className="ml-4 mt-1.5 list-disc space-y-0.5">
              <li>Use the <b>toggle</b> on each row to turn monitoring on or off. Turning it on creates alarms for that resource.</li>
              <li>Select several resources to turn monitoring on or off in <b>bulk</b>.</li>
              <li>
                Select several resources of the same type and use <b>Configure Alarms</b> to change thresholds and evaluation (M/N) at once.
                Before applying, it shows what changes for each resource. To change a single resource, use <b>Edit Alarms</b> on its detail page.
              </li>
              <li>The <b>Sync</b> button re-collects the latest resources for the account/region scope you choose.</li>
            </ul>
          </>
        ),
      },
      {
        icon: LayoutGrid,
        title: "Supported Resources (29 Types)",
        body: (
          <>
            AWS resource types whose monitoring and alarms can be managed with tags.
            <div className="mt-2.5 space-y-2.5">
              {RESOURCE_GROUPS.map((g) => (
                <div key={g.label}>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                    {g.label}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {g.types.map((t) => (
                      <ResourceTypeIcon key={t} type={t} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </>
        ),
      },
      {
        icon: Bell,
        title: "Viewing Alarms",
        body: (
          <>
            The <b>Alarms</b> screen shows all alarms by state. States are <Code>OK</Code> /{" "}
            <Code>ALARM</Code> / <Code>INSUFFICIENT_DATA</Code> / <Code>OFF</Code>, and severity is shown as{" "}
            <Code>SEV-1</Code>–<Code>SEV-5</Code>. Click the <b>bell icon</b> in the top bar to open a dropdown
            of current ALARM items and jump straight to the resource.
          </>
        ),
      },
      {
        icon: Search,
        title: "Search & Filters",
        body: (
          <>
            Type a resource name in the top-bar <b>search box</b> and press Enter to filter the Resources
            screen by name. Use the <b>customer/account dropdowns</b> in the top bar to narrow the scope.
          </>
        ),
      },
      {
        icon: Boxes,
        title: "Managing Customers & Accounts",
        body: (
          <>
            Anyone can <b>create and edit</b> customers in <b>Settings</b>. Registering an AWS account under a
            customer starts collecting that account’s resources. <b>Only admins can delete</b> a customer
            (see permissions below).
          </>
        ),
      },
    ],
  },
  {
    id: "arch",
    label: "Architecture & Integration",
    intro: "What this tool does, why, and how it works.",
    items: [
      {
        icon: Lightbulb,
        title: "In Short — Why a Central Stack",
        body: (
          <>
            A <b>single</b> stack in a central AWS account manages CloudWatch alarms across many customer
            AWS accounts in one place, <b>driven by tags</b>. Customer accounts hold <b>only an IAM Role</b>,
            with no heavy resources, and the central account reaches them via STS AssumeRole. The UI calls
            one central API, and alarm policy and code are managed consistently in one place.
          </>
        ),
      },
      {
        icon: Network,
        title: "Architecture Diagram",
        body: (
          <Block>{`Browser
  │ HTTPS
  ▼
AWS Amplify (Next.js SSR)
  · Google sign-in   · /api proxy (injects ID token)
  │ Authorization: Bearer <Google ID token>
  ▼
API Gateway (HTTP API) ──[ JWT Authorizer: Google ]
  │
  ▼
api_handler  Lambda
  ├─▶ DynamoDB      customers, accounts, thresholds, jobs, inventory, user settings
  ├─▶ CloudWatch    list / create / delete alarms
  ├─▶ STS AssumeRole ─▶ customer AWS account (read resources, alarm CRUD)
  └─▶ SQS FIFO ─▶ sqs_worker Lambda   (bulk jobs)

EventBridge Scheduler ─▶ daily_monitor Lambda
     └ scheduled: iterate accounts → scan resources → reconcile alarms

CloudWatch alarm fires ─▶ SNS Topic ─▶ alerts (Slack, email, ops team)`}</Block>
        ),
      },
      {
        icon: Share2,
        title: "Cross-Account Integration — Why / How",
        body: (
          <>
            Reading resources and creating alarms in a customer account requires permissions in that account.
            The customer account gets <b>only an IAM Role</b> (trusting the central account), and the central
            Lambda accesses it via{" "}
            <b>AssumeRole</b>. Account details (account_id, role) are registered in{" "}
            <Code>AccountsTable</Code>.
            <Block>{`Central account (this stack)      Customer AWS account
┌────────────────────┐           ┌──────────────────────────┐
│ api_handler /      │ AssumeRole │ IAM Role (trusts central) │
│ daily_monitor      │──────────▶ │   · read EC2/RDS/ELB…     │
│   Lambda           │           │   · CloudWatch alarm CRUD │
└────────────────────┘           └──────────────────────────┘
  ※ No Lambda/DB in customer accounts — IAM Role only (lightweight onboarding).`}</Block>
            <div className="mt-3">
              <b>Customer Onboarding (Console)</b>
              <div className="mt-2 flex flex-wrap gap-2">
                <a
                  href="https://console.aws.amazon.com/cloudformation/home?region=ap-northeast-2#/stacks/create/review?templateURL=https%3A%2F%2Falarm-manager-onboarding-949501913924.s3.amazonaws.com%2Fcustomer-onboarding.yaml&stackName=alarm-manager-onboarding&param_CentralAccountId=949501913924&param_CentralAlertBusArn=arn%3Aaws%3Aevents%3Aus-east-1%3A949501913924%3Aevent-bus%2Faws-monitoring-alert-dev"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white transition hover:brightness-110"
                >
                  <ExternalLink size={13} /> Create CloudFormation Stack (One Click)
                </a>
                <a
                  href="/customer-onboarding.yaml"
                  download
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
                >
                  <Download size={13} /> Download Template (YAML)
                </a>
              </div>
              <ol className="ml-4 mt-3 list-decimal space-y-1">
                <li>Click <b>Create CloudFormation Stack (One Click)</b> — the console opens in the <b>Seoul region</b> with the template and parameters (<Code>CentralAccountId</Code>, <Code>CentralAlertBusArn</Code>) <b>pre-filled</b>.</li>
                <li>If your alarms are in a <b>region other than Seoul</b>, switch to that region in the top right of the console. IAM roles are global, but the alarm event forwarding rule is a <b>regional resource</b>, so it only sees alarms in the region where it lives.</li>
                <li>At the bottom, check <b>“I acknowledge that AWS CloudFormation might create IAM resources”</b> (CAPABILITY_NAMED_IAM) → <b>Create stack</b>.</li>
                <li><b>If your alarms span several regions</b>, create one stack per region. From the second one on, set <Code>CreateSharedRoles</Code> to <Code>no</Code> and put the first stack’s <Code>AlertForwardRoleArn</Code> output into <Code>ExistingAlertForwardRoleArn</Code>. IAM roles are global, so they only need to be created once.</li>
                <li>After creation, copy <b><Code>RoleArn</Code> from Outputs</b> → in the app, go to <b>Settings → Register Account</b> (account_id, role_arn, customer). Once registered, the central event bus is <b>automatically allowed</b> to receive this account’s alarm events.</li>
              </ol>
              <details className="mt-2">
                <summary className="cursor-pointer text-xs font-medium text-slate-500 hover:text-slate-700">Deploy with the CLI (Alternative)</summary>
                <Block>{`# Deploy the customer-onboarding.yaml downloaded above (with customer account credentials)
aws cloudformation deploy \\
  --template-file customer-onboarding.yaml \\
  --stack-name alarm-manager-onboarding \\
  --capabilities CAPABILITY_NAMED_IAM \\
  --parameter-overrides CentralAccountId=<central account ID>`}</Block>
              </details>
              <p className="mt-2">
                The stack creates only an IAM Role (resource read + CloudWatch alarm CRUD + tag write, trusting only the central account)
                and an EventBridge rule and role for forwarding alarm events. No Lambda or DB is created.
                The central Lambda then assumes the registered <Code>role_arn</Code> via{" "}
                <Code>AssumeRole</Code> (session name <Code>MonitoringEngine</Code>) to read that account’s
                resources and manage alarms, and alarm state changes reach the central bus through the forwarding rule.
              </p>
            </div>
          </>
        ),
      },
      {
        icon: Workflow,
        title: "Key Flows (Tag-Based)",
        body: (
          <>
            <Block>{`[Monitoring toggle ON]
 UI toggle → api_handler → AssumeRole (if another account)
   → tag the resource (Monitoring=on, threshold tags)
   → CloudWatch PutMetricAlarm + tags (ManagedBy/Severity)
   → write ResourceInventory → refresh UI

[Scheduled sync — reconcile]
 Scheduler → daily_monitor → iterate accounts, AssumeRole
   → scan resource tags → compare/reconcile alarms → update inventory/history

[Alarm fires → alert]
 metric exceeds threshold → CloudWatch ALARM → SNS → ops team`}</Block>
            An alarm’s threshold, severity and on/off state are all determined by <b>resource tags</b> — hence
            “tag-based”.
          </>
        ),
      },
    ],
  },
  {
    id: "trouble",
    label: "Troubleshooting (FAQ)",
    items: [
      {
        icon: SlidersHorizontal,
        title: "The screen is empty",
        body: <>Check that you are <b>listed among the customer’s managers</b>, and that a different customer or account isn’t selected in the top bar.</>,
      },
      {
        icon: KeyRound,
        title: "Unauthorized / I keep getting signed out",
        body: <>Your session may have expired. Sign in again. If it keeps happening, ask an operator to check the auth settings (domain/redirect URI).</>,
      },
      {
        icon: Wrench,
        title: "The first response is slow",
        body: <>With low traffic, a serverless (Lambda) cold start can make the first request 1–2 seconds slower. Later requests are fast.</>,
      },
      {
        icon: Cloud,
        title: "Page not found (404)",
        body: <>Check that the URL includes the <b>branch prefix</b> (e.g. <Code>main.</Code>). The domain without the prefix is not served.</>,
      },
    ],
  },
];

export default function HelpPage() {
  const sections = SECTIONS;

  return (
    <main className="min-h-screen bg-surface">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/80 px-4 py-3 backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl items-center justify-between">
          <span className="font-headline text-base font-bold tracking-tight text-slate-900">
            Alarm Manager
          </span>
          <Link
            href="/"
            className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-slate-800"
          >
            <ArrowLeft size={14} /> Back to Home
          </Link>
        </div>
      </header>

      <div className="mx-auto max-w-3xl space-y-10 p-8">
      <div>
        <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
          User Guide
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Using, deploying and troubleshooting Alarm Manager, all in one place.
        </p>
        {/* 목차 */}
        <nav className="mt-4 flex flex-wrap gap-2">
          {sections.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
            >
              {s.label}
            </a>
          ))}
        </nav>
      </div>

      {sections.map((section) => (
        <section key={section.id} id={section.id} className="scroll-mt-20 space-y-4">
          <div>
            <h2 className="text-xl font-bold text-slate-900">{section.label}</h2>
            {section.intro && <p className="mt-0.5 text-sm text-slate-500">{section.intro}</p>}
          </div>
          <div className="space-y-3">
            {section.items.map((item) => (
              <div
                key={item.title}
                className="flex gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-soft"
              >
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <item.icon size={20} />
                </span>
                <div className="min-w-0">
                  <h3 className="text-base font-semibold text-slate-800">{item.title}</h3>
                  <div className="mt-1 text-sm leading-relaxed text-slate-600">{item.body}</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
      </div>
    </main>
  );
}

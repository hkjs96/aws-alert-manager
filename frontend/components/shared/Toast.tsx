'use client';

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useMemo,
  type ReactNode,
} from 'react';
import { CheckCircle, XCircle, AlertTriangle, Info, X } from 'lucide-react';

// --- Types ---

type ToastVariant = 'success' | 'error' | 'warning' | 'info';

interface ToastItem {
  id: string;
  variant: ToastVariant;
  message: string;
  duration: number;
}

interface ToastContextValue {
  showToast: (variant: ToastVariant, message: string, duration?: number) => void;
}

// --- Constants ---

const DEFAULT_DURATION = 5000;

const VARIANT_CONFIG: Record<ToastVariant, { border: string; icon: typeof CheckCircle; iconColor: string }> = {
  success: { border: 'border-green-600', icon: CheckCircle, iconColor: 'text-green-600' },
  error:   { border: 'border-red-600',   icon: XCircle,     iconColor: 'text-red-600' },
  warning: { border: 'border-amber-600',  icon: AlertTriangle, iconColor: 'text-amber-600' },
  info:    { border: 'border-blue-600',   icon: Info,        iconColor: 'text-blue-600' },
};

// --- Context ---

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return ctx;
}

// --- Individual Toast ---

function Toast({ item, onDismiss }: { item: ToastItem; onDismiss: (id: string) => void }) {
  const config = VARIANT_CONFIG[item.variant];
  const Icon = config.icon;

  useEffect(() => {
    const timer = setTimeout(() => onDismiss(item.id), item.duration);
    return () => clearTimeout(timer);
  }, [item.id, item.duration, onDismiss]);

  return (
    <div
      data-testid="toast-item"
      className={`flex items-start gap-3 max-w-sm w-full bg-white border-l-4 ${config.border} shadow-lg rounded-r-lg p-4 animate-slide-in`}
      role="alert"
    >
      <Icon className={`w-5 h-5 shrink-0 mt-0.5 ${config.iconColor}`} />
      <p className="flex-1 text-sm text-slate-800">{item.message}</p>
      <button
        onClick={() => onDismiss(item.id)}
        className="shrink-0 text-slate-400 hover:text-slate-600"
        aria-label="닫기"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

// --- Container ---

function ToastContainer({ toasts, onDismiss }: { toasts: ToastItem[]; onDismiss: (id: string) => void }) {
  if (toasts.length === 0) return null;

  return (
    <div
      data-testid="toast-container"
      className="fixed top-4 right-4 z-[100] flex flex-col gap-2"
    >
      {toasts.map((t) => (
        <Toast key={t.id} item={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

// --- Provider ---

let toastCounter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (variant: ToastVariant, message: string, duration: number = DEFAULT_DURATION) => {
      const id = `toast-${++toastCounter}`;
      setToasts((prev) => [...prev, { id, variant, message, duration }]);
    },
    [],
  );

  // 매 렌더마다 새 객체를 내려보내면 토스트 하나가 뜨고 질 때마다 useToast를 쓰는
  // 모든 컴포넌트가 리렌더된다. Provider는 앱 루트에 있어 영향 범위가 전체다.
  const value = useMemo(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

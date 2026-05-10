'use client';

import { Loader2 } from 'lucide-react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost';
type Size = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
  children?: ReactNode;
}

const variantClasses: Record<Variant, string> = {
  primary: 'bg-primary text-white hover:brightness-110 shadow-sm shadow-primary/20',
  secondary: 'bg-white text-slate-700 border border-slate-200 hover:bg-slate-50 hover:border-slate-300',
  danger: 'bg-red-600 text-white hover:bg-red-700 shadow-sm',
  ghost: 'text-slate-600 hover:bg-slate-100 hover:text-slate-800',
};

const sizeClasses: Record<Size, string> = {
  sm: 'px-3 py-1.5 text-xs gap-1.5',
  md: 'px-4 py-2 text-sm gap-2',
  lg: 'px-5 py-2.5 text-sm gap-2',
};

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  children,
  disabled,
  className = '',
  ...rest
}: ButtonProps) {
  const baseClasses = 'inline-flex items-center justify-center font-semibold rounded-lg transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed';
  const variantClass = variantClasses[variant];
  const sizeClass = sizeClasses[size];
  const combinedClassName = `${baseClasses} ${variantClass} ${sizeClass} ${className}`;

  return (
    <button
      className={combinedClassName}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? (
        <Loader2 size={14} className="animate-spin" />
      ) : (
        icon && icon
      )}
      {children}
    </button>
  );
}

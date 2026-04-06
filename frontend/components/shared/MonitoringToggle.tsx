"use client";

interface MonitoringToggleProps {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  size?: "sm" | "lg";
  disabled?: boolean;
}

export function MonitoringToggle({
  enabled,
  onChange,
  size = "sm",
  disabled = false,
}: MonitoringToggleProps) {
  const isLarge = size === "lg";
  const trackClass = isLarge ? "h-7 w-[52px]" : "h-5 w-9";
  const thumbClass = isLarge ? "h-5 w-5" : "h-3.5 w-3.5";
  const translateClass = isLarge
    ? (enabled ? "translate-x-6" : "translate-x-1")
    : (enabled ? "translate-x-4" : "translate-x-0.5");

  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      disabled={disabled}
      onClick={() => onChange(!enabled)}
      className={`
        relative inline-flex shrink-0 cursor-pointer items-center rounded-full
        transition-colors duration-200 ease-in-out
        focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent
        disabled:cursor-not-allowed disabled:opacity-50
        ${trackClass}
        ${enabled ? "bg-accent" : "bg-gray-300"}
      `}
    >
      <span
        className={`
          inline-block rounded-full bg-white shadow-sm
          transition-transform duration-200 ease-in-out
          ${thumbClass} ${translateClass}
        `}
      />
    </button>
  );
}

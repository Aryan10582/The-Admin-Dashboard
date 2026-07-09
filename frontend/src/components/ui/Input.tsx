import type { InputHTMLAttributes } from "react";
import { clsx } from "clsx";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={clsx(
        "h-10 w-full rounded-md border border-border bg-white px-3 text-sm outline-none ring-primary transition focus:ring-2",
        className
      )}
      {...props}
    />
  );
}

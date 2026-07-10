import { forwardRef, type InputHTMLAttributes } from "react";
import { clsx } from "clsx";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref
) {
  return (
    <input
      ref={ref}
      className={clsx(
        "h-10 w-full rounded-md border border-border bg-white px-3 text-sm outline-none ring-primary transition focus:ring-2",
        className
      )}
      {...props}
    />
  );
});

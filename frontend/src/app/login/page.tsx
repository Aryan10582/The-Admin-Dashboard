"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { login } from "@/lib/auth";

type LoginFormValues = {
  email: string;
  password: string;
};

export default function LoginPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors }
  } = useForm<LoginFormValues>({
    defaultValues: {
      email: "",
      password: ""
    },
    mode: "onSubmit"
  });

  const mutation = useMutation({
    mutationFn: (values: LoginFormValues) => login(values.email, values.password),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["current-admin"] });
      router.replace("/dashboard");
    },
    onError: (loginError: Error) => {
      setError(loginError.message);
    }
  });

  function onSubmit(values: LoginFormValues) {
    setError(null);
    mutation.mutate(values);
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
      <section className="w-full max-w-sm rounded-lg border border-border bg-white p-6 shadow-sm">
        <div className="mb-6">
          <h1 className="text-xl font-semibold">Admin Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">Sign in to continue.</p>
        </div>
        <form className="space-y-4" noValidate onSubmit={handleSubmit(onSubmit)}>
          <label className="block space-y-2">
            <span className="text-sm font-medium">Email</span>
            <Input
              type="email"
              autoComplete="email"
              aria-invalid={Boolean(errors.email)}
              {...register("email", {
                required: "Email is required",
                pattern: {
                  value: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
                  message: "Enter a valid email address"
                }
              })}
            />
            {errors.email ? <span className="text-sm text-red-600">{errors.email.message}</span> : null}
          </label>
          <label className="block space-y-2">
            <span className="text-sm font-medium">Password</span>
            <Input
              type="password"
              autoComplete="current-password"
              aria-invalid={Boolean(errors.password)}
              {...register("password", { required: "Password is required" })}
            />
            {errors.password ? <span className="text-sm text-red-600">{errors.password.message}</span> : null}
          </label>
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          <Button className="w-full" type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Signing in..." : "Sign in"}
          </Button>
        </form>
      </section>
    </main>
  );
}

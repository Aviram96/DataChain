"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { networkErrorMessage } from "@/lib/api";
import { AuthApiError, login } from "@/lib/auth-api";
import { setAccessToken } from "@/lib/auth-token";

import { useAuth } from "./auth-provider";
import { useToast } from "./toast-provider";

export function LoginForm() {
  const router = useRouter();
  const { refreshSession } = useAuth();
  const { showToast } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);

    try {
      const token = await login({ email, password });
      setAccessToken(token.access_token);
      await refreshSession();
      showToast("Signed in successfully.", "success");
      router.push("/");
    } catch (error) {
      if (error instanceof AuthApiError && error.status === 401) {
        showToast(error.message, "error");
      } else if (error instanceof AuthApiError) {
        showToast(error.message, "error");
      } else {
        showToast(networkErrorMessage(), "error");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1">
        <label htmlFor="email" className="block text-sm text-slate-300">
          Email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 outline-none ring-emerald-500/50 focus:ring-2"
        />
      </div>
      <div className="space-y-1">
        <label htmlFor="password" className="block text-sm text-slate-300">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 outline-none ring-emerald-500/50 focus:ring-2"
        />
      </div>
      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-60"
      >
        {submitting ? "Signing in…" : "Sign in"}
      </button>
      <p className="text-center text-sm text-slate-400">
        No account?{" "}
        <Link href="/register" className="text-emerald-400 hover:text-emerald-300">
          Register
        </Link>
      </p>
    </form>
  );
}

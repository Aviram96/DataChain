"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { networkErrorMessage } from "@/lib/api";
import { AuthApiError, login } from "@/lib/auth-api";
import { setAccessToken } from "@/lib/auth-token";
import { ui } from "@/lib/ui";

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
      showToast("Logged in successfully.", "success");
      router.push("/cameras");
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
      <div className="space-y-1.5">
        <label htmlFor="email" className={ui.label}>
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
          className={ui.input}
        />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="password" className={ui.label}>
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
          className={ui.input}
        />
      </div>
      <button
        type="submit"
        disabled={submitting}
        className={`w-full ${ui.btnPrimary}`}
      >
        {submitting ? "Logging in…" : "Log in"}
      </button>
      <p className={`text-center ${ui.muted}`}>
        No account?{" "}
        <Link href="/register" className={ui.link}>
          Sign up
        </Link>
      </p>
    </form>
  );
}

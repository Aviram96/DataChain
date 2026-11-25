"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { networkErrorMessage } from "@/lib/api";
import { AuthApiError, login, register } from "@/lib/auth-api";
import { setAccessToken } from "@/lib/auth-token";
import {
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  PASSWORD_REQUIREMENTS_HINT,
  passwordRequirementsError,
} from "@/lib/password-requirements";
import { ui } from "@/lib/ui";

import { useAuth } from "./auth-provider";
import { useToast } from "./toast-provider";

export function RegisterForm() {
  const router = useRouter();
  const { refreshSession } = useAuth();
  const { showToast } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const requirementError = passwordRequirementsError(password);
    if (requirementError) {
      showToast(requirementError, "error");
      return;
    }

    setSubmitting(true);

    try {
      await register({ email, password });
      const token = await login({ email, password });
      setAccessToken(token.access_token);
      await refreshSession();
      showToast("Registration successful. Welcome to Datachain.", "success");
      router.push("/cameras");
    } catch (error) {
      if (error instanceof AuthApiError && error.status === 409) {
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
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
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
          autoComplete="new-password"
          required
          minLength={PASSWORD_MIN_LENGTH}
          maxLength={PASSWORD_MAX_LENGTH}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-describedby="password-requirements"
          className={ui.input}
        />
        <p id="password-requirements" className={ui.hint}>
          {PASSWORD_REQUIREMENTS_HINT}
        </p>
      </div>
      <button
        type="submit"
        disabled={submitting}
        className={`w-full ${ui.btnPrimary}`}
      >
        {submitting ? "Creating account…" : "Sign up"}
      </button>
      <p className={`text-center ${ui.muted}`}>
        Already have an account?{" "}
        <Link href="/login" className={ui.link}>
          Log in
        </Link>
      </p>
    </form>
  );
}

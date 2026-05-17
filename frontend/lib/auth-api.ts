import { getApiBaseUrl, parseApiErrorMessage } from "./api";
import { authFetch } from "./auth-fetch";
import { getAccessToken } from "./auth-token";

export type LoginPayload = {
  email: string;
  password: string;
};

export type RegisterPayload = {
  email: string;
  password: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
};

export type UserPublic = {
  id: string;
  email: string;
  created_at: string;
};

export class AuthApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "AuthApiError";
  }
}

export async function login(payload: LoginPayload): Promise<TokenResponse> {
  const response = await fetch(`${getApiBaseUrl()}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const message = await parseApiErrorMessage(
      response,
      "Incorrect email or password.",
    );
    throw new AuthApiError(message, response.status);
  }

  return (await response.json()) as TokenResponse;
}

export async function register(payload: RegisterPayload): Promise<void> {
  const response = await fetch(`${getApiBaseUrl()}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const fallback =
      response.status === 409
        ? "An account with this email already exists."
        : "Registration failed. Please try again.";
    const message = await parseApiErrorMessage(response, fallback);
    throw new AuthApiError(message, response.status);
  }
}

export async function getCurrentUser(): Promise<UserPublic | null> {
  if (!getAccessToken()) {
    return null;
  }

  const response = await authFetch(`${getApiBaseUrl()}/auth/me`);

  if (response.status === 401) {
    return null;
  }

  if (!response.ok) {
    const message = await parseApiErrorMessage(
      response,
      "Could not load your profile.",
    );
    throw new AuthApiError(message, response.status);
  }

  return (await response.json()) as UserPublic;
}

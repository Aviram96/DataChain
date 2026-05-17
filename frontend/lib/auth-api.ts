import { getApiBaseUrl, parseApiErrorMessage } from "./api";

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

/** Matches backend ``UserRegister`` password rules in ``app/schemas/auth.py``. */

export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 64;

/** Printable ASCII except space: letters, numbers, and special characters. */
const PASSWORD_ALLOWED = /^[!-~]+$/;

export const PASSWORD_REQUIREMENTS_HINT =
  "Use 8–64 characters. English letters, numbers, and special characters are allowed.";

const UNSUPPORTED_CHARACTERS =
  "Password can contain only English letters, numbers, and special characters.";

/**
 * Returns a user-facing error message when the password fails requirements,
 * or null when it is valid for registration.
 */
export function passwordRequirementsError(password: string): string | null {
  if (password.length < PASSWORD_MIN_LENGTH) {
    return "Password must be at least 8 characters.";
  }
  if (password.length > PASSWORD_MAX_LENGTH) {
    return "Password must be at most 64 characters.";
  }
  if (!PASSWORD_ALLOWED.test(password)) {
    return UNSUPPORTED_CHARACTERS;
  }
  return null;
}

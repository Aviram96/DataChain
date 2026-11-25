import assert from "node:assert/strict";
import test from "node:test";

import {
  PASSWORD_REQUIREMENTS_HINT,
  passwordRequirementsError,
} from "./password-requirements.ts";

const UNSUPPORTED =
  "Password can contain only English letters, numbers, and special characters.";

test("the registration hint states the character policy", () => {
  assert.equal(
    PASSWORD_REQUIREMENTS_HINT,
    "Use 8–64 characters. English letters, numbers, and special characters are allowed."
  );
});

test("a 7-character password is rejected", () => {
  assert.equal(
    passwordRequirementsError("abcdefg"),
    "Password must be at least 8 characters."
  );
  assert.equal(
    passwordRequirementsError("1234567"),
    "Password must be at least 8 characters."
  );
});

test("8 and 64 character passwords of one character type are accepted", () => {
  for (const password of [
    "abcdefgh",
    "ABCDEFGH",
    "12345678",
    "!@#$%^&*",
    "a".repeat(64),
    "1".repeat(64),
    "!".repeat(64),
  ]) {
    assert.equal(passwordRequirementsError(password), null);
  }
});

test("Hebrew, emoji, and spaces are rejected", () => {
  assert.equal(passwordRequirementsError("א".repeat(8)), UNSUPPORTED);
  assert.equal(passwordRequirementsError("abc😀defg"), UNSUPPORTED);
  assert.equal(passwordRequirementsError(" abcdefg"), UNSUPPORTED);
  assert.equal(passwordRequirementsError("abcdefgh "), UNSUPPORTED);
});

test("a 65-character password is rejected", () => {
  assert.equal(
    passwordRequirementsError("a".repeat(65)),
    "Password must be at most 64 characters."
  );
  assert.equal(
    passwordRequirementsError("!".repeat(65)),
    "Password must be at most 64 characters."
  );
});

// Mirrors the backend rules in app/schemas/auth.py so users see problems before submitting.
// The API still validates everything; these checks are only for faster feedback.

export const USERNAME_RULE = "3-30 characters: lowercase letters, numbers and underscores";
export const PASSWORD_RULE = "At least 8 characters, with a letter and a number";

export function validateEmail(email: string): string | undefined {
  if (!email.trim()) return "Email is required.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return "Enter a valid email address.";
}

export function validateUsername(username: string): string | undefined {
  if (!username.trim()) return "Username is required.";
  if (!/^[a-z0-9_]{3,30}$/.test(username.trim().toLowerCase())) return `Username must be ${USERNAME_RULE.toLowerCase()}.`;
}

export function validatePassword(password: string): string | undefined {
  if (!password) return "Password is required.";
  if (password.length < 8) return "Password must be at least 8 characters.";
  if (password.length > 128) return "Password must be at most 128 characters.";
  if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) return "Password must contain a letter and a number.";
}

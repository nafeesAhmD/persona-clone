/** Safe user info returned by the API. The password hash is never sent. */
export interface User {
  id: string;
  email: string;
  username: string;
  full_name: string | null;
  is_active: boolean;
  /** Read-only: set on the server (CLI), never by the browser. */
  is_admin: boolean;
  created_at: string;
}

export interface RegisterInput {
  email: string;
  username: string;
  full_name: string;
  password: string;
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface ProfileUpdate {
  full_name?: string | null;
  username?: string;
}

export interface PasswordChange {
  current_password: string;
  new_password: string;
}

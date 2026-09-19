"use client";

import { useId, useState, type FormEvent } from "react";

import { useAuth } from "@/providers/AuthProvider";
import { useHealth } from "@/providers/HealthProvider";

export function LoginScreen() {
  const auth = useAuth();
  const health = useHealth();
  const usernameId = useId();
  const passwordId = useId();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await auth.login(username, password);
    } catch {
      // auth.loginError already holds the message; nothing else to do here.
    }
  }

  return (
    <div className="login-screen">
      <form className="login-form" onSubmit={onSubmit} noValidate>
        <h1>ReadyTrader-Crypto</h1>
        <p className="login-form__subtitle">Sign in to view the operator dashboard.</p>

        {auth.sessionNotice && (
          <p className="login-form__notice" role="status">
            {auth.sessionNotice}
          </p>
        )}

        {!health.reachable && health.loaded && (
          <p className="login-form__notice login-form__notice--warning" role="status">
            Can&apos;t reach the API at {health.apiUrl} yet. You can still try to sign in once it&apos;s up.
          </p>
        )}

        <div className="form-field">
          <label htmlFor={usernameId}>Username</label>
          <input
            id={usernameId}
            name="username"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </div>

        <div className="form-field">
          <label htmlFor={passwordId}>Password</label>
          <input
            id={passwordId}
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>

        {auth.loginError && (
          <p className="login-form__error" role="alert" data-testid="login-error">
            {auth.loginError}
          </p>
        )}

        <button type="submit" disabled={auth.loginPending}>
          {auth.loginPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

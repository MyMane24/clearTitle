import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { API, setToken, AuthResponse } from '../api/backend';
import clearTitleLogo from '../assets/clearTitle.png';

interface Props {
  onAuthed: (auth: AuthResponse) => void;
}

export function AuthScreen({ onAuthed }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!email || !password) {
      setError('Email and password are required.');
      return;
    }
    if (mode === 'register' && password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setBusy(true);
    try {
      const auth = mode === 'login'
        ? await API.login(email, password)
        : await API.register(email, password, fullName);
      setToken(auth.access_token);
      onAuthed(auth);
    } catch (err: any) {
      setError(err.message || 'Authentication failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ctd-root auth-root">
      <div className="auth-card">
        <Link to="/" className="auth-logo-link" title="Back to home">
          <img src={clearTitleLogo} className="auth-logo" alt="clearTitle" />
        </Link>
        <h2 className="auth-title">
          {mode === 'login' ? 'Sign in to ClearTitle' : 'Create your account'}
        </h2>
        <p className="auth-sub">Karnataka Property Title Verification</p>

        <form onSubmit={submit}>
          {mode === 'register' && (
            <input
              className="auth-input"
              placeholder="Full name (optional)"
              value={fullName}
              onChange={e => setFullName(e.target.value)}
            />
          )}
          <input
            className="auth-input"
            type="email"
            placeholder="Email"
            value={email}
            autoComplete="email"
            onChange={e => setEmail(e.target.value)}
          />
          <input
            className="auth-input"
            type="password"
            placeholder="Password"
            value={password}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            onChange={e => setPassword(e.target.value)}
          />

          {error && <div className="auth-error">{error}</div>}

          <button className="btn btn-primary auth-btn" disabled={busy} type="submit">
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign In' : 'Create Account'}
          </button>
        </form>

        <button
          className="auth-toggle"
          onClick={() => { setMode(m => (m === 'login' ? 'register' : 'login')); setError(''); }}
        >
          {mode === 'login'
            ? "Don't have an account? Register"
            : 'Already have an account? Sign in'}
        </button>
      </div>
    </div>
  );
}

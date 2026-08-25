import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Eye, EyeOff, FileCheck2, GitMerge, Loader2, Lock, Mail, ShieldCheck, User2, Zap,
} from 'lucide-react';
import { API, setToken, AuthResponse } from '../api/backend';

interface Props {
  onAuthed: (auth: AuthResponse) => void;
}

function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
    </svg>
  );
}

export function AuthScreen({ onAuthed }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [showPw, setShowPw] = useState(false);
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

  const toggleMode = () => {
    setMode(m => (m === 'login' ? 'register' : 'login'));
    setError('');
    setShowPw(false);
  };

  const googleLogin = () => {
    setError('Google Sign-In is not available yet. Please sign in with your email instead.');
  };

  return (
    <div className="ctd-root auth-screen">
      {/* Left Column: Brand Story Panel (~45%) */}
      <aside className="auth-left">
        <div className="auth-left-grid" />
        <div className="auth-left-rings" />
        <div className="auth-left-orb auth-left-orb-a" />
        <div className="auth-left-orb auth-left-orb-b" />
        <div className="auth-left-edge" />

        <div className="auth-left-inner">
          <Link to="/" className="auth-brand" title="Back to home">
            <span className="auth-brand-title">clear<span className="auth-brand-title-grad">Title</span></span>
          </Link>

          <div className="auth-hero">
            <h1 className="auth-hero-title">
              Title verification,
              <br />
              <span className="auth-hero-word">
                done right.
                <span className="auth-hero-underline" />
              </span>
            </h1>
            <p className="auth-hero-desc">
              AI-powered property document analysis and title verification for complete legal clarity and compliance.
            </p>
          </div>

          <div className="auth-features">
            <div className="auth-feature">
              <div className="auth-feature-icon"><FileCheck2 size={19} /></div>
              <span>Documents Cross-Verification</span>
            </div>
            <div className="auth-feature">
              <div className="auth-feature-icon"><GitMerge size={19} /></div>
              <span>Title Chain Audit</span>
            </div>
            <div className="auth-feature">
              <div className="auth-feature-icon"><Zap size={19} /></div>
              <span>Instant Report and Document Security</span>
            </div>
          </div>
        </div>

        <div className="auth-trust">
          <ShieldCheck size={16} />
          <span>Secure Intelligent Title Intelligence</span>
        </div>
      </aside>

      {/* Right Column: Login Card (~55%) */}
      <section className="auth-right">
        <div className="auth-right-orb" />
        <div className="auth-right-grid" />

        <div className="auth-card-modern">
          <div className="auth-card-head">
            <p className="auth-kicker">WELCOME BACK</p>
            <h2 className="auth-heading">
              {mode === 'login' ? 'Sign in to clearTitle' : 'Create your account'}
            </h2>
            <p className="auth-heading-sub">
              {mode === 'login'
                ? 'Access your workspace and verified reports.'
                : 'Start verifying property documents today.'}
            </p>
          </div>

          <button className="auth-google-btn" onClick={googleLogin} type="button">
            <GoogleIcon />
            <span>Continue with Google</span>
          </button>

          <div className="auth-divider">
            <div className="auth-divider-line" />
            <span>or sign in with email</span>
            <div className="auth-divider-line" />
          </div>

          <form onSubmit={submit} className="auth-form">
            {mode === 'register' && (
              <div className="auth-field">
                <label className="auth-label" htmlFor="auth-fullname">
                  FULL NAME <span className="auth-optional">(OPTIONAL)</span>
                </label>
                <div className="auth-input-wrap">
                  <span className="auth-input-icon"><User2 size={16} /></span>
                  <input
                    id="auth-fullname"
                    className="auth-input"
                    type="text"
                    placeholder="Your name"
                    value={fullName}
                    autoComplete="name"
                    onChange={e => setFullName(e.target.value)}
                  />
                </div>
              </div>
            )}

            <div className="auth-field">
              <label className="auth-label" htmlFor="auth-email">EMAIL ADDRESS</label>
              <div className="auth-input-wrap">
                <span className="auth-input-icon"><Mail size={16} /></span>
                <input
                  id="auth-email"
                  className="auth-input"
                  type="email"
                  placeholder="you@company.com"
                  value={email}
                  autoComplete="email"
                  onChange={e => setEmail(e.target.value)}
                />
              </div>
            </div>

            <div className="auth-field">
              <div className="auth-label-row">
                <label className="auth-label" htmlFor="auth-password">PASSWORD</label>
                {mode === 'login' && (
                  <a
                    className="auth-forgot"
                    href="#"
                    onClick={e => {
                      e.preventDefault();
                      setError('Password reset is not available yet. Please contact support.');
                    }}
                  >
                    Forgot password?
                  </a>
                )}
              </div>
              <div className="auth-input-wrap">
                <span className="auth-input-icon"><Lock size={16} /></span>
                <input
                  id="auth-password"
                  className="auth-input auth-input-pw"
                  type={showPw ? 'text' : 'password'}
                  placeholder="••••••••"
                  value={password}
                  autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                  onChange={e => setPassword(e.target.value)}
                />
                <button
                  className="auth-pw-toggle"
                  type="button"
                  aria-label="Toggle password visibility"
                  onClick={() => setShowPw(s => !s)}
                >
                  {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {error && <div className="auth-error">{error}</div>}

            <button className="auth-submit-btn" disabled={busy} type="submit">
              {busy && <Loader2 size={15} className="auth-spin" />}
              {busy ? 'Please wait…' : mode === 'login' ? 'Sign in to clearTitle' : 'Create Account'}
            </button>
          </form>

          <p className="auth-foot">
            {mode === 'login' ? (
              <>New to clearTitle? <button className="auth-toggle" onClick={toggleMode}>Create account</button></>
            ) : (
              <>Already have an account? <button className="auth-toggle" onClick={toggleMode}>Sign in</button></>
            )}
          </p>
        </div>

        <div className="auth-secure-note">
          <Lock size={14} />
          <span>Secured by 256-bit encryption</span>
        </div>
      </section>
    </div>
  );
}

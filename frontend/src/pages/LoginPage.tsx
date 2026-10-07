import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import '../dashboard/dashboard.css';
import { AuthScreen } from '../dashboard/AuthScreen';
import { getToken, setToken } from '../api/backend';

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const linkCase = searchParams.get('link');
  const token = searchParams.get('token');
  const oauthError = searchParams.get('error');

  useEffect(() => {
    if (token) {
      setToken(token);
      navigate(linkCase ? `/app?link=${encodeURIComponent(linkCase)}` : '/app', { replace: true });
      return;
    }
    if (getToken()) navigate('/app', { replace: true });
  }, [navigate, token, linkCase]);

  return (
    <AuthScreen
      initialError={oauthError ? 'Google sign-in failed. Please try again or use email.' : ''}
      onAuthed={() => {
        navigate(linkCase ? `/app?link=${encodeURIComponent(linkCase)}` : '/app');
      }}
    />
  );
}

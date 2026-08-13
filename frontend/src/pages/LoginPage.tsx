import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import '../dashboard/dashboard.css';
import { AuthScreen } from '../dashboard/AuthScreen';
import { getToken } from '../api/backend';

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  useEffect(() => {
    if (getToken()) navigate('/app', { replace: true });
  }, [navigate]);

  const linkCase = searchParams.get('link');

  return (
    <AuthScreen
      onAuthed={() => {
        navigate(linkCase ? `/app?link=${encodeURIComponent(linkCase)}` : '/app');
      }}
    />
  );
}

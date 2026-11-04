import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Dashboard } from './components/dashboard/Dashboard';
import { LoginForm } from './components/auth/LoginForm';
import { useAuth } from './hooks/useAuth';

export const App: React.FC = () => {
  const { isAuthenticated, checkAuth } = useAuth();

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={isAuthenticated ? <Navigate to="/" replace /> : <LoginForm />} />
        <Route path="/" element={isAuthenticated ? <Dashboard /> : <Navigate to="/login" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
};

export default App;


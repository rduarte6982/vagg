import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import '@/i18n';
import { LoginPage } from '@/pages/Login';
import { AuthProvider } from '@/lib/auth-context';

describe('LoginPage', () => {
  it('renders email and password fields', () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(screen.getByLabelText(/E-mail|Email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Senha|Password/i)).toBeInTheDocument();
  });
});

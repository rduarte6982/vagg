/**
 * VAGG mark — quatro nós + agregador central. 28x28 base.
 * Espelha o componente do server UI pra manter a marca consistente.
 */
import type { FC } from 'react';

export const VaggMark: FC<{ size?: number }> = ({ size = 28 }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 28 28"
    width={size}
    height={size}
    style={{ flexShrink: 0 }}
    aria-hidden="true"
  >
    <circle cx="4" cy="4" r="2" fill="#b6bbc2" />
    <circle cx="24" cy="4" r="2" fill="#b6bbc2" />
    <circle cx="4" cy="24" r="2" fill="#b6bbc2" />
    <circle cx="24" cy="24" r="2" fill="#b6bbc2" />
    <path d="M4 4  L14 14" stroke="#7a808a" strokeWidth="1.4" fill="none" />
    <path d="M24 4  L14 14" stroke="#7a808a" strokeWidth="1.4" fill="none" />
    <path d="M4 24 L14 14" stroke="#7a808a" strokeWidth="1.4" fill="none" />
    <path d="M24 24 L14 14" stroke="#7a808a" strokeWidth="1.4" fill="none" />
    <rect x="10" y="10" width="8" height="8" rx="1.6" fill="oklch(78% 0.16 162)" />
  </svg>
);

export const VaggLogo: FC<{ size?: number; wordmarkSize?: 'sm' | 'md' | 'lg' }> = ({
  size = 28,
  wordmarkSize = 'md',
}) => {
  const tx =
    wordmarkSize === 'sm' ? 'text-sm' : wordmarkSize === 'lg' ? 'text-2xl' : 'text-lg';
  return (
    <span className="inline-flex items-center gap-2.5">
      <VaggMark size={size} />
      <span className={`vagg-wordmark text-vagg-ink ${tx}`}>
        vagg<span className="dot">.</span>
      </span>
    </span>
  );
};

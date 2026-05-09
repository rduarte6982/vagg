/**
 * VAGG · brand mark + wordmark (cobrand ROIT).
 *
 * Mark: 4 nós roteando para um core dourado (paleta ROIT). Geometria
 * "agregador de rede" mantida. Cores trocadas pra navy + gold.
 *
 * Wordmark: "vagg." em monospace com dot gold (acento ROIT).
 *
 * Props:
 *   - size: tamanho do mark em px (default 28)
 *   - showWordmark: se true, mostra "vagg." ao lado
 *   - tone: 'default' (gold core) | 'muted' (sem gold) | 'inverse' (sobre paper)
 */
import { type FC } from 'react';

interface VaggLogoProps {
  size?: number;
  showWordmark?: boolean;
  tone?: 'default' | 'muted' | 'inverse';
  className?: string;
  wordmarkSize?: 'sm' | 'md' | 'lg';
}

export const VaggMark: FC<{ size?: number; tone?: 'default' | 'muted' | 'inverse' }> = ({
  size = 28,
  tone = 'default',
}) => {
  // Em dark (default) os nós são cream sobre navy + core gold.
  // Em inverse (sobre paper) os nós ficam navy + core gold.
  const nodeFill = tone === 'inverse' ? '#14283b' : 'var(--roit-ink-2)';
  const wireStroke = tone === 'inverse' ? '#5a5749' : 'var(--roit-line-2)';
  const coreFill = tone === 'muted' ? 'var(--roit-ink-3)' : 'var(--roit-gold)';

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 28 28"
      width={size}
      height={size}
      style={{ flexShrink: 0 }}
      aria-hidden="true"
    >
      <circle cx="4" cy="4" r="2" fill={nodeFill} />
      <circle cx="24" cy="4" r="2" fill={nodeFill} />
      <circle cx="4" cy="24" r="2" fill={nodeFill} />
      <circle cx="24" cy="24" r="2" fill={nodeFill} />
      <path d="M4 4  L14 14" stroke={wireStroke} strokeWidth="1.4" fill="none" />
      <path d="M24 4  L14 14" stroke={wireStroke} strokeWidth="1.4" fill="none" />
      <path d="M4 24 L14 14" stroke={wireStroke} strokeWidth="1.4" fill="none" />
      <path d="M24 24 L14 14" stroke={wireStroke} strokeWidth="1.4" fill="none" />
      {/* Core: square gold (mimetizando o dot do "i" do logo ROIT) */}
      <rect x="10" y="10" width="8" height="8" rx="1" fill={coreFill} />
    </svg>
  );
};

export const VaggLogo: FC<VaggLogoProps> = ({
  size = 28,
  showWordmark = true,
  tone = 'default',
  className = '',
  wordmarkSize = 'md',
}) => {
  const wordmarkClass =
    wordmarkSize === 'sm'
      ? 'text-sm'
      : wordmarkSize === 'lg'
        ? 'text-2xl'
        : 'text-lg';

  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <VaggMark size={size} tone={tone} />
      {showWordmark && (
        <span className="inline-flex flex-col items-start leading-none">
          <span className={`vagg-wordmark ${wordmarkClass}`}>
            vagg<span className="dot">.</span>
          </span>
          <span
            className="text-[9px] font-semibold tracking-[0.2em] mt-1"
            style={{ color: 'var(--roit-gold)' }}
          >
            BY ROIT
          </span>
        </span>
      )}
    </span>
  );
};

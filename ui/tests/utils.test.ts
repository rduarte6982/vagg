import { describe, expect, it } from 'vitest';
import { cn } from '@/lib/utils';

describe('cn', () => {
  it('merges class names', () => {
    expect(cn('a', 'b')).toBe('a b');
  });

  it('drops falsy classes', () => {
    expect(cn('a', false, undefined, 'b')).toBe('a b');
  });

  it('lets later tailwind utilities win', () => {
    expect(cn('p-2', 'p-4')).toBe('p-4');
  });
});

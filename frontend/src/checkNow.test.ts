import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from './api';
import { checkNow, MAX_WAIT_MS, POLL_MS } from './checkNow';

vi.mock('./api', () => ({ api: { checkNow: vi.fn(), checker: vi.fn() } }));
const sleep = vi.fn(async () => undefined);

beforeEach(() => vi.clearAllMocks());

describe('checkNow', () => {
  it('returns at once when no check was started (too soon, or the request failed)', async () => {
    vi.mocked(api.checkNow).mockResolvedValueOnce({ started: false, checkedAt: 'a' });
    await checkNow(() => true, sleep);
    vi.mocked(api.checkNow).mockRejectedValueOnce(new Error('offline'));
    await checkNow(() => true, sleep);
    expect(sleep).not.toHaveBeenCalled();
    expect(api.checker).not.toHaveBeenCalled();
  });

  it('waits until the last-checked time moves', async () => {
    vi.mocked(api.checkNow).mockResolvedValueOnce({ started: true, checkedAt: 'a' });
    vi.mocked(api.checker)
      .mockResolvedValueOnce({ checkedAt: 'a' })
      .mockRejectedValueOnce(new Error('blip'))
      .mockResolvedValueOnce({ checkedAt: 'b' });
    await checkNow(() => true, sleep);
    expect(api.checker).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledWith(POLL_MS);
  });

  it('gives up after the time limit, or when the screen is gone', async () => {
    vi.mocked(api.checkNow).mockResolvedValue({ started: true, checkedAt: null });
    vi.mocked(api.checker).mockResolvedValue({ checkedAt: null });
    await checkNow(() => true, sleep);
    expect(api.checker).toHaveBeenCalledTimes(Math.ceil(MAX_WAIT_MS / POLL_MS));
    vi.mocked(api.checker).mockClear();
    await checkNow(() => false, sleep);
    expect(api.checker).not.toHaveBeenCalled();
  });
});

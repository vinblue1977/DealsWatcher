import { api } from './api';
import type { Config } from './config';

/** What the notifications control should show on this device. */
export type PushState = 'needs-install' | 'unsupported' | 'blocked' | 'off' | 'on';

let publicKey = '';

export function initPush(config: Config): void {
  publicKey = config.vapidPublicKey ?? '';
}

/** Running as the installed Home Screen app (iPhones only allow push there). */
export function isInstalled(): boolean {
  const standalone = (navigator as { standalone?: boolean }).standalone === true;
  return standalone || (typeof matchMedia === 'function' && matchMedia('(display-mode: standalone)').matches);
}

const isIOS = (): boolean =>
  /iPhone|iPad|iPod/.test(navigator.userAgent ?? '') || (navigator.platform === 'MacIntel' && (navigator.maxTouchPoints ?? 0) > 1); // iPadOS

/** The service worker, or an error if it never starts (a failed registration would otherwise wait forever). */
async function ready(): Promise<ServiceWorkerRegistration> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error('The app’s background worker is not running. Close the app and open it again.')), 5000);
  });
  try {
    // Registering again is harmless, and says clearly when the worker can't start.
    await navigator.serviceWorker.register('/sw.js').catch(() => {
      throw new Error('The app’s background worker could not start. Close the app and open it again.');
    });
    return await Promise.race([navigator.serviceWorker.ready, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

const canPush = (): boolean => 'serviceWorker' in navigator && 'PushManager' in globalThis && 'Notification' in globalThis;

/** The server's public key as the bytes the browser wants. */
export function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

async function subscription(): Promise<PushSubscription | null> {
  return (await ready()).pushManager.getSubscription();
}

export async function pushState(): Promise<PushState> {
  if (!canPush()) return !isInstalled() && isIOS() ? 'needs-install' : 'unsupported'; // only iPhones need the install step
  if (Notification.permission === 'denied') return 'blocked';
  const sub = await subscription();
  if (!sub) return 'off';
  return (await api.pushStatus(sub.endpoint)).thisDevice ? 'on' : 'off'; // the server may have dropped it (expired)
}

/** Asks permission, subscribes this device and tells the server. Call it straight from a tap. */
export async function enablePush(): Promise<void> {
  if (!publicKey) throw new Error('Notifications are not set up on the server yet.');
  if ((await Notification.requestPermission()) !== 'granted') throw new Error('Notifications were not allowed. You can change that in iOS Settings.');
  const registration = await ready();
  const before = await registration.pushManager.getSubscription();
  const options = { userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) };
  let sub: PushSubscription;
  try {
    sub = await registration.pushManager.subscribe(options);
  } catch (e) {
    if ((e as Error).name !== 'InvalidStateError' || !before) throw e;
    await before.unsubscribe(); // made with another key (the server's key changed): replace it
    sub = await registration.pushManager.subscribe(options);
  }
  try {
    await api.pushOn(sub.toJSON(), Intl.DateTimeFormat().resolvedOptions().timeZone);
  } catch (e) {
    if (!before || before.endpoint !== sub.endpoint) await sub.unsubscribe(); // keep one the device already had; drop a new one the server refused
    throw e;
  }
}

export async function disablePush(): Promise<void> {
  const sub = await subscription();
  if (!sub) return;
  await api.pushOff(sub.endpoint);
  await sub.unsubscribe();
}

/** Sends a test notification to this user's devices; throws if none received it. */
export async function testPush(): Promise<void> {
  const sub = await subscription();
  if (!sub) throw new Error('Notifications are off on this device.');
  if ((await api.pushTest(sub.endpoint)).sent < 1) throw new Error('The test did not reach a device. Try turning notifications off and on again.');
}

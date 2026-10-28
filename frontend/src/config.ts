// Written by the deploy next to the app: this stack's API and sign-in settings.
export interface Config {
  apiUrl: string;
  authUrl: string;
  clientId: string;
  region?: string;
  vapidPublicKey?: string;
}

const KEPT = 'dw.config';

function keep(config?: Config): Config | null {
  try {
    if (config) localStorage.setItem(KEPT, JSON.stringify(config));
    else return JSON.parse(localStorage.getItem(KEPT) ?? 'null');
  } catch {
    /* storage blocked */
  }
  return null;
}

export async function loadConfig(): Promise<Config> {
  let res: Response;
  try {
    res = await fetch('/config.json', { cache: 'no-store' });
  } catch (e) {
    const kept = keep(); // offline: the settings from the last visit
    if (kept) return kept;
    throw e;
  }
  if (!res.ok) throw new Error('App settings are missing. Please try again later.');
  let config: Config;
  try {
    config = await res.json();
  } catch {
    config = {} as Config; // CloudFront answers a missing file with the app's HTML page (status 200)
  }
  if (typeof config.apiUrl !== 'string' || typeof config.authUrl !== 'string' || typeof config.clientId !== 'string') {
    throw new Error('App settings are missing. Please try again later.');
  }
  keep(config);
  return config;
}

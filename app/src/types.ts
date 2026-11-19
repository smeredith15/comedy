export type PlatformKind = 'subscription' | 'free' | 'ads' | 'early_access' | 'paid' | 'tv' | string;

export interface PlatformLink {
  platform: string;
  kind?: PlatformKind;
  url?: string;
  date?: string;
}

export interface Special {
  id: string;
  title: string;
  performers: string[];
  status?: 'released' | 'upcoming' | 'announced';
  format?: 'hour' | 'half_hour';
  runtime_min?: number;
  release_date?: string;
  public_release_date?: string;
  platforms?: PlatformLink[];
  ids?: { tmdb?: string; imdb?: string; youtube?: string; wikipedia?: string };
  first_seen?: string;
}

export interface PlatformInfo {
  name: string;
  kind?: PlatformKind;
  color?: string;
  search_url?: string;
}

export interface Db {
  version: number;
  generated: string;
  last_run?: string;
  repo?: string | null;
  region?: string;
  counts?: Record<string, number>;
  specials: Special[];
  comedians: Record<string, { name: string; followed?: boolean }>;
  platforms: Record<string, PlatformInfo>;
  redirects: Record<string, string>;
}

export type MarkStatus = 'want' | 'seen' | 'not_interested';

export interface Mark {
  id: string; // special id
  status: MarkStatus | null;
  rating?: number; // 1-5
  notes?: string;
  watches: string[]; // YYYY-MM-DD, rewatches allowed
  updatedAt: number;
}

export interface Follow {
  slug: string;
  since: number;
}

export interface SpinEvent {
  id?: number;
  specialId: string;
  at: number;
  action: 'shown' | 'not_tonight' | 'watch' | 'seen';
}

export interface Weights {
  want: number;
  followed: number;
  recent: number;
  skipped: number;
}

export interface SpinFilters {
  pool: 'want' | 'unseen' | 'everything';
  maxRuntime: number | null;
  availability: 'mine' | 'free' | 'any';
  yearFrom: number | null;
  yearTo: number | null;
  format: 'any' | 'hour' | 'half_hour';
  skipRecentComedianDays: number | null;
}

export interface Settings {
  services: string[];
  region: string;
  weights: Weights;
  spin: SpinFilters;
  initialized: boolean;
}

export const DEFAULT_WEIGHTS: Weights = { want: 3, followed: 2, recent: 1.5, skipped: 0.5 };

export const DEFAULT_SPIN: SpinFilters = {
  pool: 'unseen',
  maxRuntime: null,
  availability: 'any',
  yearFrom: null,
  yearTo: null,
  format: 'any',
  skipRecentComedianDays: null,
};

export const DEFAULT_SETTINGS: Settings = {
  services: [],
  region: 'US',
  weights: DEFAULT_WEIGHTS,
  spin: DEFAULT_SPIN,
  initialized: false,
};

export const FREE_KINDS = new Set(['free', 'ads']);

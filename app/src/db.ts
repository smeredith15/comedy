import Dexie, { type Table } from 'dexie';
import type { Db, Follow, Mark, Settings, SpinEvent } from './types';

/** Everything personal lives here, on this device only. */
export class LocalDb extends Dexie {
  marks!: Table<Mark, string>;
  follows!: Table<Follow, string>;
  spins!: Table<SpinEvent, number>;
  kv!: Table<{ key: string; value: unknown }, string>;

  constructor(name = 'specials-tracker') {
    super(name);
    this.version(1).stores({
      marks: 'id, status, updatedAt',
      follows: 'slug',
      spins: '++id, specialId, at, action',
      kv: 'key',
    });
  }

  async getSettings(): Promise<Settings | undefined> {
    return (await this.kv.get('settings'))?.value as Settings | undefined;
  }

  async putSettings(s: Settings) {
    await this.kv.put({ key: 'settings', value: s });
  }

  async getCachedData(): Promise<Db | undefined> {
    return (await this.kv.get('data'))?.value as Db | undefined;
  }

  async putCachedData(d: Db) {
    await this.kv.put({ key: 'data', value: d });
  }
}

export const local = new LocalDb();

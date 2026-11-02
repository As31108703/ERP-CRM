/**
 * 安全的瀏覽器儲存：localStorage／sessionStorage 被停用或丟出例外時（例如無痕模式、配額已滿），
 * 改存在記憶體 Map，並把 `volatile` 設為 true，讓介面提示「重新整理後不會保留」。
 */
export interface SafeStorage {
  get(key: string): string | null;
  set(key: string, value: string): boolean;
  remove(key: string): void;
  readonly volatile: boolean;
}

export function createSafeStorage(getStore: () => Storage): SafeStorage {
  const memory = new Map<string, string>();
  let volatile = false;

  function fallback(): void {
    volatile = true;
  }

  return {
    get(key) {
      if (!volatile) {
        try {
          return getStore().getItem(key);
        } catch {
          fallback();
        }
      }
      return memory.get(key) ?? null;
    },
    set(key, value) {
      if (!volatile) {
        try {
          getStore().setItem(key, value);
          return true;
        } catch {
          fallback();
        }
      }
      memory.set(key, value);
      return true;
    },
    remove(key) {
      memory.delete(key);
      if (!volatile) {
        try {
          getStore().removeItem(key);
        } catch {
          fallback();
        }
      }
    },
    get volatile() {
      return volatile;
    },
  };
}

export const safeLocal: SafeStorage = createSafeStorage(() => window.localStorage);
export const safeSession: SafeStorage = createSafeStorage(() => window.sessionStorage);

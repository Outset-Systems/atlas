
export const OURS = /^atlas[.-]/;

function forget(storage) {
  const gone = [];
  try {
    for (let i = 0; i < storage.length; i++) {
      const key = storage.key(i);
      if (typeof key === 'string' && OURS.test(key)) gone.push(key);
    }
    for (const key of gone) storage.removeItem(key);
  } catch {   }
  return gone;
}

export function beginPage(local, session) {
  return [...forget(local), ...forget(session)];
}

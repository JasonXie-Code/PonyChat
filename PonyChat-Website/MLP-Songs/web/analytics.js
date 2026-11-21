/* Anonymous visit IDs and actual audible playback time; never track IPs or seek distance. */
(function () {
  'use strict';
  const audio = document.getElementById('audio');
  if (!audio) return;
  const id = () => crypto.randomUUID();
  let visitor = id();
  try {
    visitor = localStorage.getItem('music-visitor') || visitor;
    if (!/^[a-zA-Z0-9-]{16,80}$/.test(visitor)) visitor = id();
    localStorage.setItem('music-visitor', visitor);
  } catch (_) { /* Storage disabled: use a page-scoped anonymous ID. */ }
  const pending = new Map();
  let sending = false, play = null, active = false, seeking = false;
  let lastWall = performance.now(), lastPosition = audio.currentTime;
  const endpoint = '/api/analytics/events';
  function enqueue(event, key = event.id) { pending.set(key, event); }
  enqueue({kind: 'visit', id: id(), visitor});
  async function drain() {
    if (sending) return;
    sending = true;
    try {
      for (let attempt = 0; pending.size && attempt < 100; attempt++) {
        const [key, event] = pending.entries().next().value;
        const response = await fetch(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(event), keepalive: true});
        if (!response.ok) break;
        if (pending.get(key) === event) pending.delete(key);
      }
    } catch (_) { /* Retry the same IDs at the next heartbeat. */ }
    finally { sending = false; }
  }
  function sample() {
    const now = performance.now(), position = audio.currentTime;
    if (play && active && !seeking) {
      const wall = Math.max(0, (now - lastWall) / 1000);
      const advanced = Math.max(0, position - lastPosition) / (audio.playbackRate || 1);
      play.seconds += Math.min(wall, advanced);
    }
    lastWall = now; lastPosition = position;
  }
  function flush() {
    sample();
    if (play) enqueue({...play, seconds: Math.round(play.seconds * 1000) / 1000});
    drain();
  }
  audio.addEventListener('playing', () => {
    if (!play) {
      const song = window.MusicPlayer?.current();
      if (!song) return;
      play = {kind: 'play', id: id(), visitor, song: song.id, seconds: 0};
      // Preserve the zero-time start separately so a failed request can be retried in order.
      enqueue({...play}, play.id + ':start');
    }
    sample(); active = true; drain();
  });
  for (const event of ['pause', 'waiting', 'stalled', 'error']) {
    audio.addEventListener(event, () => { flush(); active = false; }, true);
  }
  for (const event of ['ended', 'loadstart', 'emptied']) {
    audio.addEventListener(event, () => { flush(); active = false; play = null; }, true);
  }
  audio.addEventListener('seeking', () => { seeking = true; sample(); }, true);
  audio.addEventListener('seeked', () => { sample(); seeking = false; }, true);
  audio.addEventListener('timeupdate', sample);
  setInterval(flush, 10000);
  document.addEventListener('visibilitychange', () => { if (document.hidden) flush(); });
  window.addEventListener('pagehide', () => {
    sample();
    if (play) enqueue({...play});
    for (const event of pending.values()) {
      navigator.sendBeacon?.(endpoint, new Blob([JSON.stringify(event)], {type: 'application/json'}));
    }
  });
  drain();
})();
